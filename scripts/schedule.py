#!/usr/bin/env python3
"""Build the seeded grading schedule the pundits plan requires, and read it back strictly.

Pundits plan, P5. The leaders queue is a sorted product ordered breadth-first,
which leaves two confounds the pundits study cannot accept. If people are graded
lean by lean, a quota stop or a judge's drift over the night lines up with lean.
If every blinded call runs before every open one, drift lines up with mode, and
the halo (open minus blinded) absorbs it. So:

  - transcripts are cut into time blocks of `block_size`;
  - within each lean, people are shuffled and their transcripts dealt round-robin,
    and the leans are interleaved, so every block mixes leans;
  - inside a block, each (transcript, judge) runs both modes back to back, and a
    seeded coin decides which mode goes first;
  - optional drift anchors: fixed transcripts re-graded in both modes by every
    judge once per `anchor_every` blocks, as run 1, 2, ...

A person with no lean label is refused rather than placed in a guessed stratum.
The manifest never contains a lean label: lean labels are private, and the
manifest is an operational file.

  schedule.py build --transcripts data-pundits/transcripts_blind \
      --lean-labels data-pundits/private/lean_labels.json \
      --judges fable,astra,gemini --block-size 20 --seed 20260914 \
      --anchors slug/source,slug/source --anchor-every 4 \
      --out data-pundits/logs/schedule/pilot.jsonl

Then: grade.py --study pundits --schedule data-pundits/logs/schedule/pilot.jsonl ...
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODES = ("blinded", "open")
FIELDS = ("block", "slug", "source_id", "judge", "mode", "run")


def build_schedule(items: list[tuple[str, str]], leans: dict[str, str], judges: list[str],
                   block_size: int = 20, seed: int = 0,
                   anchors: list[tuple[str, str]] | None = None,
                   anchor_every: int | None = None) -> list[dict]:
    if block_size < 1:
        raise ValueError("block_size must be at least 1")
    if not judges:
        raise ValueError("no judges")
    items = sorted(set(items))
    missing = sorted({slug for slug, _ in items if slug not in leans})
    if missing:
        raise RuntimeError(f"no lean label for {missing}; the schedule is stratified by lean and never "
                           f"guesses one")
    anchors = list(anchors or [])
    unknown = [a for a in anchors if a not in set(items)]
    if unknown:
        raise RuntimeError(f"anchor transcripts {unknown} are not in the schedule's transcripts")
    if anchors and not anchor_every:
        raise ValueError("anchors need anchor_every")

    rng = random.Random(seed)
    by_lean: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for slug, sid in items:
        by_lean[leans[slug]][slug].append(sid)

    queues: dict[str, list[tuple[str, str]]] = {}
    for lean in sorted(by_lean):
        people = sorted(by_lean[lean])
        rng.shuffle(people)
        stacks = {p: sorted(by_lean[lean][p]) for p in people}
        for p in people:
            rng.shuffle(stacks[p])
        q: list[tuple[str, str]] = []
        while any(stacks.values()):
            for p in people:
                if stacks[p]:
                    q.append((p, stacks[p].pop()))
        queues[lean] = q

    lean_order = sorted(queues)
    rng.shuffle(lean_order)
    order: list[tuple[str, str]] = []
    while any(queues.values()):
        for lean in lean_order:
            if queues[lean]:
                order.append(queues[lean].pop(0))

    entries: list[dict] = []

    def emit(slug: str, sid: str, block: int, run: int) -> None:
        for judge in judges:
            first = rng.choice(MODES)
            for mode in (first, MODES[1] if first == MODES[0] else MODES[0]):
                entries.append({"block": block, "slug": slug, "source_id": sid,
                                "judge": judge, "mode": mode, "run": run})

    n_blocks = math.ceil(len(order) / block_size)
    for b in range(n_blocks):
        for slug, sid in order[b * block_size:(b + 1) * block_size]:
            emit(slug, sid, b, 0)
        if anchors and (b + 1) % anchor_every == 0:
            group = (b + 1) // anchor_every
            for slug, sid in anchors:
                emit(slug, sid, b, group)
    return entries


def verified_keys(report_path: Path) -> set[tuple[str, str]]:
    """The (slug, source_id) pairs a PERSON verified, read from the P6 pilot report.

    This exists because the transcripts directory is not the eligible set.
    MEASURED 2026-09-16: `data-pundits/transcripts_blind` holds 114 recordings
    and the pilot verified 89, so scheduling the directory would send 25
    unchecked recordings to the judges. The leaders board paid 44 wrong-person
    recordings to learn that an unverified speaker reaches the published score,
    and `report.json` is the only record of who actually looked.

    An empty verified set raises rather than returning an empty allow-list. A
    filter that silently permits nothing looks identical to a filter that is
    switched off until you read the call count.
    """
    data = json.loads(Path(report_path).read_text())
    people = data.get("people") or {}
    keys = {tuple(k.split("/", 1)) for p in people.values() for k in p.get("selected_keys", [])}
    keys = {k for k in keys if len(k) == 2}
    if not keys:
        raise RuntimeError(f"{report_path} names no verified recording; refusing to treat that as "
                           f"an empty allow-list")
    return keys


def scan_panels(grades_dir: Path, judges: list[str]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Read a grades tree and split its recordings into (complete, partial).

    COMPLETE means every (judge, mode) cell of the panel holds a record that is
    really a grade: no validation errors, and at least one scored dimension.
    PARTIAL means at least one cell is a grade and at least one is not.

    A record that failed validation counts as ABSENT here, never as a cell. It
    is not a grade, and `aggregate.drop_partial_panels` will throw the whole
    recording away over it, so a scheduler that read it as present would leave
    the hole open for ever. That is the same rule `grade.py` now applies to its
    cache.
    """
    required = {(j, m) for j in judges for m in MODES}
    scored: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    seen: set[tuple[str, str]] = set()
    for p in sorted(Path(grades_dir).rglob("*.json")):
        if "_obsolete" in p.parts or "_provenance" in p.parts or p.name.endswith(".tmp"):
            continue
        d = json.loads(p.read_text())
        key = (d.get("leader_slug"), d.get("source_id"))
        if key[0] is None or key[1] is None:
            continue
        seen.add(key)
        # A repeat (run > 0) measures the judge, not the speaker, and
        # aggregate.py excludes it from every published number. Counting it as
        # a filled cell here would mark a partial recording complete and stop
        # the scheduler ever repairing it.
        if (d.get("run") or 0) != 0:
            continue
        if d.get("validation_errors") or not (d.get("grade") or {}).get("dimensions"):
            continue
        scored[key].add((d.get("judge"), d.get("mode")))
    complete = {k for k in seen if required <= scored.get(k, set())}
    partial = {k for k in seen if k not in complete and scored.get(k)}
    return complete, partial


def select_topup(items: list[tuple[str, str]], complete: set[tuple[str, str]],
                 partial: set[tuple[str, str]], target: int,
                 seed: int) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Pick enough recordings to bring each person UP TO `target` complete ones.

    Returns (picked, shortfall). `shortfall` names every person who cannot reach
    the target from the material available, with how many they are short. It is
    reported rather than absorbed: a person silently left under
    MIN_TRANSCRIPTS_TO_RANK is a person missing from the board for a reason
    nobody wrote down.

    "Grade N more each" and "bring each person to N" are different instructions
    and the pilot proved it. The first batch graded 2 per person against a rank
    floor of 5, so a second batch of 2 would have reached 4 and ranked nobody.

    A partial recording is scheduled BEFORE any new one, because its other cells
    are already scored and reuse their cache, so repairing it costs one call
    where a new recording costs four.
    """
    if target < 1:
        raise ValueError("target must be at least 1")
    rng = random.Random(seed)
    by_person: dict[str, list[str]] = defaultdict(list)
    for slug, sid in sorted(set(items)):
        by_person[slug].append(sid)

    picked: list[tuple[str, str]] = []
    shortfall: dict[str, int] = {}
    for slug in sorted(by_person):
        have = sum(1 for sid in by_person[slug] if (slug, sid) in complete)
        need = target - have
        if need <= 0:
            continue
        repairs = [sid for sid in by_person[slug] if (slug, sid) in partial]
        fresh = [sid for sid in by_person[slug]
                 if (slug, sid) not in complete and (slug, sid) not in partial]
        rng.shuffle(fresh)
        take = (sorted(repairs) + fresh)[:need]
        picked.extend((slug, sid) for sid in take)
        if len(take) < need:
            shortfall[slug] = need - len(take)
    return picked, shortfall


def write_manifest(path: Path, entries: list[dict]) -> None:
    from atomicio import write_atomic
    write_atomic(Path(path), "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))


def read_manifest(path: Path) -> list[dict]:
    entries, seen = [], set()
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        missing = [f for f in FIELDS if f not in e]
        if missing:
            raise RuntimeError(f"{path}:{n} is missing {missing}")
        if e["mode"] not in MODES or not isinstance(e["run"], int) or not isinstance(e["block"], int):
            raise RuntimeError(f"{path}:{n} has an invalid mode, run or block: {e}")
        key = (e["slug"], e["source_id"], e["judge"], e["mode"], e["run"])
        if key in seen:
            raise RuntimeError(f"{path}:{n} duplicates {key}")
        seen.add(key)
        entries.append(e)
    if not entries:
        raise RuntimeError(f"{path} holds no entries")
    return entries


def main() -> int:
    import study_profile as SP
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--transcripts", required=True)
    b.add_argument("--lean-labels", required=True, help="JSON object {slug: lean}. Private; never copied into the manifest.")
    b.add_argument("--judges", required=True)
    b.add_argument("--block-size", type=int, default=20)
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--anchors", default="", help="Comma-separated slug/source_id transcripts to re-grade per group.")
    b.add_argument("--anchor-every", type=int, default=None)
    b.add_argument("--out", required=True)
    b.add_argument("--graded", default=None,
                   help="Existing grades tree. With --target-per-person, recordings whose panel is "
                        "already complete are skipped and partial ones are repaired first.")
    b.add_argument("--target-per-person", type=int, default=None,
                   help="Schedule up to this many COMPLETE recordings per person, counting what "
                        "--graded already holds. This is a target, not a quantity to add.")
    b.add_argument("--verified", default=None,
                   help="P6 pilot report.json. Only recordings a person verified are scheduled; "
                        "the transcripts directory also holds unverified ones.")
    SP.add_study_arg(b)
    args = ap.parse_args()
    paths = [args.transcripts, args.lean_labels, args.out]
    paths += [p for p in (args.graded, args.verified) if p]
    SP.guard(args.study, *paths)
    if (args.target_per_person is None) != (args.graded is None):
        raise SystemExit("REFUSING: --target-per-person and --graded are used together; a target "
                         "without the existing grades would recount from zero and re-grade the corpus")
    items = [(p.parent.name, p.stem) for p in sorted(Path(args.transcripts).rglob("*.json"))
             if not p.name.endswith(".tmp")]
    leans = json.loads(Path(args.lean_labels).read_text())
    if args.verified:
        allowed = verified_keys(Path(args.verified))
        dropped = [i for i in items if i not in allowed]
        items = [i for i in items if i in allowed]
        print(f"verified filter: {len(items)} of {len(items) + len(dropped)} transcripts on disk "
              f"were verified by a person; {len(dropped)} unverified are not scheduled", file=sys.stderr)
        if not items:
            raise SystemExit("REFUSING: no transcript on disk is in the verified set")
    if args.target_per_person is not None:
        judges = [j.strip() for j in args.judges.split(",") if j.strip()]
        complete, partial = scan_panels(Path(args.graded), judges)
        items, shortfall = select_topup(items, complete, partial, args.target_per_person, args.seed)
        print(f"top-up to {args.target_per_person} per person: {len(complete)} recordings already "
              f"complete, {len(partial)} partial to repair, {len(items)} scheduled", file=sys.stderr)
        if shortfall:
            print("SHORT of material, these people stay below the target: "
                  + ", ".join(f"{s} by {n}" for s, n in sorted(shortfall.items())), file=sys.stderr)
        if not items:
            raise SystemExit("REFUSING: every person is already at the target; nothing to schedule")
    anchors = [tuple(a.split("/", 1)) for a in args.anchors.split(",") if a.strip()]
    try:
        entries = build_schedule(items, leans, [j.strip() for j in args.judges.split(",") if j.strip()],
                                 args.block_size, args.seed, anchors, args.anchor_every)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
    write_manifest(Path(args.out), entries)
    blocks = max(e["block"] for e in entries) + 1
    print(f"wrote {args.out}: {len(entries)} calls over {len(items)} transcripts in {blocks} blocks, seed {args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
