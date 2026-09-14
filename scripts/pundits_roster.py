#!/usr/bin/env python3
"""Check the pundits roster and its private lean labels before anything reads them.

Pundits plan, P6. The roster drives discovery, blinding and grading, and the
lean labels drive the schedule strata and the bias diagnostics. A missing field
there does not fail loudly downstream: blind_study() skips an absent handle,
discovery skips an absent channel, and the schedule refuses only at build time.
So the whole shape is checked once, here:

  - every entry carries slug, name, role, company, show, outlet, handles,
    own_channels, identity_tokens and archival, with the right types;
  - `company` equals `show` or `outlet`, because leaders-era tools
    (qa_transcripts, discover_sources) still read `company`;
  - an own channel names its URL, its channel name and how it was verified;
  - an archival subject carries `last_recording_date`, which sets its window;
  - no roster entry carries a lean label, because the roster is readable by
    tooling that the labels must never reach;
  - every roster slug has exactly one label in {left, right, heterodox}, every
    label has a roster slug, and every label cites at least one outside source;
  - the lean groups differ in size by at most `max_imbalance`.

  .venv/bin/python scripts/pundits_roster.py \
      --roster data-pundits/roster/final.json \
      --lean-labels data-pundits/private/lean_labels.json \
      --lean-sources data-pundits/private/lean_sources.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LEANS = ("left", "right", "heterodox")
STRINGS = ("slug", "name", "role", "company", "show", "outlet")
LISTS = ("handles", "own_channels", "identity_tokens")
CHANNEL_FIELDS = ("url", "channel_name", "verified_by")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRIVATE_KEYS = ("lean", "lean_sources", "lean_disputed", "lean_alternative")


def roster_errors(roster: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: Counter = Counter()
    for i, p in enumerate(roster):
        where = f"roster[{i}] {p.get('slug', '?')}"
        for f in STRINGS:
            if not isinstance(p.get(f), str) or not p[f].strip():
                errors.append(f"{where}: `{f}` must be a non-empty string")
        for f in LISTS:
            if not isinstance(p.get(f), list):
                errors.append(f"{where}: `{f}` must be a list")
        if not isinstance(p.get("archival"), bool):
            errors.append(f"{where}: `archival` must be true or false")
        leaked = [k for k in PRIVATE_KEYS if k in p]
        if leaked:
            errors.append(f"{where}: carries private lean fields {leaked}; they belong only in the private files")
        slug = p.get("slug")
        if isinstance(slug, str):
            seen[slug] += 1
            if not SLUG.match(slug):
                errors.append(f"{where}: slug is not lowercase-hyphenated")
        if isinstance(p.get("company"), str) and p.get("company") not in (p.get("show"), p.get("outlet")):
            errors.append(f"{where}: `company` must equal `show` or `outlet`")
        tokens = p.get("identity_tokens")
        if isinstance(tokens, list) and (len(tokens) < 2 or not all(isinstance(t, str) and t.strip() for t in tokens)):
            errors.append(f"{where}: `identity_tokens` needs at least 2 non-empty strings")
        handles = p.get("handles")
        if isinstance(handles, list) and not all(isinstance(h, str) and h.strip() for h in handles):
            errors.append(f"{where}: every handle must be a non-empty string")
        for j, ch in enumerate(p.get("own_channels") or [] if isinstance(p.get("own_channels"), list) else []):
            missing = [f for f in CHANNEL_FIELDS if not isinstance(ch, dict) or not str(ch.get(f, "")).strip()]
            if missing:
                errors.append(f"{where}: own_channels[{j}] is missing {missing}")
            elif not ch["url"].startswith("https://www.youtube.com/"):
                errors.append(f"{where}: own_channels[{j}] url is not a youtube.com URL")
        if p.get("archival") is True and not (isinstance(p.get("last_recording_date"), str)
                                              and DATE.match(p["last_recording_date"])):
            errors.append(f"{where}: an archival subject needs `last_recording_date` as YYYY-MM-DD")
    errors += [f"slug `{s}` appears {n} times" for s, n in sorted(seen.items()) if n > 1]
    return errors


def label_errors(roster: list[dict], leans: dict, sources: dict, max_imbalance: int = 2) -> list[str]:
    errors: list[str] = []
    slugs = {p.get("slug") for p in roster}
    for s in sorted(slugs - set(leans)):
        errors.append(f"`{s}` has no lean label")
    for s in sorted(set(leans) - slugs):
        errors.append(f"lean label for `{s}`, who is not on the roster")
    for s, lean in sorted(leans.items()):
        if lean not in LEANS:
            errors.append(f"`{s}` has lean `{lean}`, not one of {list(LEANS)}")
        cited = sources.get(s)
        if not isinstance(cited, list) or not cited or not all(
                isinstance(c, dict) and str(c.get("url", "")).startswith("http") and str(c.get("quote", "")).strip()
                for c in cited):
            errors.append(f"`{s}` has no outside source with a url and a quote")
    counts = Counter(leans[s] for s in slugs if s in leans)
    if counts and max(counts[l] for l in LEANS) - min(counts[l] for l in LEANS) > max_imbalance:
        errors.append(f"lean groups are unbalanced: {dict(counts)} differ by more than {max_imbalance}")
    return errors


def main() -> int:
    import study_profile as SP
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--roster", required=True)
    ap.add_argument("--lean-labels", required=True)
    ap.add_argument("--lean-sources", required=True)
    ap.add_argument("--max-imbalance", type=int, default=2)
    SP.add_study_arg(ap)
    args = ap.parse_args()
    SP.guard(args.study, args.roster, args.lean_labels, args.lean_sources)
    roster = json.loads(Path(args.roster).read_text())["roster"]
    leans = json.loads(Path(args.lean_labels).read_text())
    sources = json.loads(Path(args.lean_sources).read_text())
    errors = roster_errors(roster) + label_errors(roster, leans, sources, args.max_imbalance)
    for e in errors:
        print(f"ERROR {e}")
    counts = Counter(leans.get(p["slug"]) for p in roster)
    print(f"{len(roster)} people, leans {dict(counts)}, "
          f"{sum(1 for p in roster if not p['own_channels'])} without a verified own channel, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
