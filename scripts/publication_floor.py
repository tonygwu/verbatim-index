#!/usr/bin/env python3
"""A board that collapsed must not publish over the board that did not.

WHAT THIS GUARDS. Membership introduced a new way for the leaders board to empty
itself. A typo such as "leader" for "leaders" across membership.json is valid
JSON, names no unknown slug, and passes every structural check; every grade then
lands off-board, the page renders zero leaders, and deploy.sh publishes it,
because deploy.sh prints the leader count and applies no floor.

WHY THE FLOOR IS THE PREVIOUS PUBLISHED COUNT. Decided by the operator on
2026-09-17, over two cheaper derivations, both of which were rejected with their
costs understood:

  roster size                 refuses for ever from P3, because the roster then
                              carries seven people who publish only on the
                              predictions board and are never scored
  membership's leaders board  survives P3, but still refuses when a real leader
                              legitimately drops under MIN_TRANSCRIPTS_TO_RANK,
                              which one withdrawal is enough to cause and which
                              has already happened once, to C.C. Wei
  previous published count    the only one of the three that also catches a
                              board eroding slowly, 50 to 40 over weeks

Its costs were accepted rather than avoided: it needs state, it needs a
first-run bootstrap, and it needs a tolerance that cannot be derived.

WHERE THE STATE LIVES, AND WHY NOT THE OBVIOUS PLACE. AGENTS.md records that
deploy.sh stays READ-ONLY ON DATA, and the only write to the production data
source in that script is the --refresh aggregate. So the previous count may not
be written into the data repository. It goes beside site/index.html, which
deploy.sh already writes, and is committed to the PUBLIC repo so every clone
reads the same number through git. The failure mode that leaves is a deploy from
a clone that has not pulled, reading a stale count; --data-revision already pins
the data side, and code staleness is a hazard this repo already carries.

THE TOLERANCE IS A TYPED NUMBER AND THERE IS NO WAY TO DERIVE ONE. It therefore
sits in exactly one place, is named, and is PRINTED ON EVERY RUN whether or not
it fires. A guard whose threshold is invisible until it refuses is a guard an
operator learns to bypass, which is the failure this repo has already recorded
for AGGREGATE FAILED.

THE FIRST RUN HAS NO PREVIOUS COUNT, and says so loudly. A silent pass would
make the one deploy that cannot be guarded look guarded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

#: The only threshold in this file. A published board may lose up to this
#: fraction of the previous one before publication is refused. 0.15 tolerates a
#: withdrawal sweep of 7 off a board of 50, and refuses the 50-to-42 erosion the
#: operator named. Chosen loose on purpose: the plan records that too tight a
#: guard prints a refusal every cycle and trains the operator to bypass it.
MAX_DROP_FRACTION = 0.15

STATE_NAME = "published.json"


def state_path(site_dir: str | Path) -> Path:
    return Path(site_dir) / STATE_NAME


def read_previous(site_dir: str | Path) -> dict | None:
    """The last recorded publication, or None on the first run.

    A malformed file RAISES rather than being treated as absent: "I cannot read
    the previous count" and "there is no previous count" are different facts,
    and only one of them is safe to continue from.
    """
    p = state_path(site_dir)
    if not p.is_file():
        return None
    try:
        prev = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{p} is not valid JSON: {exc}. It records the last published "
                           f"leader count and the floor cannot be applied without it. "
                           f"Fix or delete it deliberately; deleting it takes the "
                           f"bootstrap path, which publishes without a floor.") from exc
    if not isinstance(prev, dict) or not isinstance(prev.get("leaders_published"), int):
        raise RuntimeError(f"{p} carries no integer leaders_published; got "
                           f"{prev if not isinstance(prev, dict) else prev.get('leaders_published')!r}")
    return prev


def floor_for(previous_count: int) -> int:
    """The smallest count that may publish against `previous_count`."""
    return int(previous_count * (1.0 - MAX_DROP_FRACTION))


def check(count: int, previous: dict | None) -> tuple[bool, str]:
    """(may_publish, the line to print). Always returns a line, never silence."""
    if previous is None:
        return True, (f"PUBLICATION FLOOR: no previous publication recorded, so this run "
                      f"BOOTSTRAPS the floor at {count} leaders and is NOT guarded. "
                      f"Every later run is checked against it.")
    prev_n = previous["leaders_published"]
    floor = floor_for(prev_n)
    when = previous.get("published_at_utc", "an unrecorded time")
    if count < floor:
        return False, (f"REFUSING: about to publish {count} leaders against {prev_n} "
                       f"published at {when}. The floor is {floor}, which is "
                       f"{prev_n} less {MAX_DROP_FRACTION:.0%}. A drop this large is a "
                       f"collapsed board rather than a withdrawal: check membership.json "
                       f"and the aggregate before publishing. Override by recording a new "
                       f"baseline deliberately, never by widening the tolerance.")
    return True, (f"publication floor: {count} leaders against {prev_n} previously "
                  f"published, floor {floor} ({MAX_DROP_FRACTION:.0%} tolerance)"
                  + (f", DOWN {prev_n - count}" if count < prev_n else ""))


def record(site_dir: str | Path, count: int, results_path: str | Path,
           data_revision: str | None = None) -> Path:
    """Write the new baseline. Called only after a publication succeeded."""
    rp = Path(results_path)
    digest = hashlib.sha256(rp.read_bytes()).hexdigest() if rp.is_file() else None
    payload = {
        "leaders_published": count,
        # UTC, explicitly. The repo forbids deriving logical time from the local
        # clock, and a publication stamp read by another clone must not depend on
        # the hour the publishing machine happens to be in.
        "published_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results_sha256": digest,
        "data_revision": data_revision,
    }
    p = state_path(site_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=1) + "\n")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("check", "record"))
    ap.add_argument("--site-dir", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--results", default=None, help="results.json, fingerprinted on record")
    ap.add_argument("--data-revision", default=None)
    args = ap.parse_args()

    if args.action == "check":
        ok, line = check(args.count, read_previous(args.site_dir))
        print(line)
        return 0 if ok else 1

    p = record(args.site_dir, args.count, args.results or "/nonexistent", args.data_revision)
    print(f"publication floor: recorded {args.count} leaders in {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
