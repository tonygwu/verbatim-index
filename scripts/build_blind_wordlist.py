#!/usr/bin/env python3
"""Decide which single-word company aliases are ordinary English, and freeze it.

`blind()` redacts every alias unconditionally. The alias lists come from
`discover_sources.aliases_for()`, which splits a multi-word company name and
adds each part as its own alias, so "Advanced Machine Intelligence Labs" puts
the bare words "Machine" and "Intelligence" on the list. Those words then
vanish from ordinary prose. See "The blinder replaces ordinary English words"
in AGENTS.md for the measurement.

Two signals are needed, because each covers the other's failure:

  DICTIONARY   /usr/share/dict/words, plus simple plural stripping because the
               list holds no plurals and "games" is one of the worst offenders.
               It is `web2`, 236k entries including proper nouns, so on its own
               it calls "Elon" and "Musk" English words. It is right about the
               cases that matter here: "uber" and "google" are not in it.

  SPREAD       the share of a token's LOWERCASE uses that fall outside the
               leader who owns the alias. An ordinary word is used by everyone.
               A company name is used by the people who work there. On its own
               it misjudges "google" at 81% outside, because everyone talks
               about Google, which is exactly the case the dictionary catches.

A token counts as ordinary only if BOTH agree. Ordinary tokens are still
redacted where they appear CAPITALISED, which is how the company is written.
That is the same capitalisation heuristic `fuzzy_targets()` already relies on.

The decision is FROZEN to a file rather than computed at blinding time, because
spread is a property of the corpus and the corpus grows. A transcript must
blind the same way today and next month, so the list is generated deliberately,
committed, and re-generated only when someone means to change it.

Run: .venv/bin/python scripts/build_blind_wordlist.py [--write]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_transcripts import in_dictionary, load_dictionary  # noqa: E402

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True,
                           check=True).stdout.strip())
OUT = ROOT / "scripts" / "blind_wordlist.json"

# Chosen from the observed distribution, not by feel. Sorted by spread, the
# candidates run ... 0.76 Face, 0.73 Games, then a gap to 0.61 Playground,
# 0.42 Epic. 0.70 sits in the empty band, so the cutoff describes the data
# rather than rounding a number. Run --show to re-read the distribution.
SPREAD_THRESHOLD = 0.70

# Below this many lowercase occurrences corpus-wide, spread is noise rather
# than signal: "Prometheus" appeared once and scored a spread of 1.00. A token
# this rare is left redacted, which is the safe direction.
MIN_OCCURRENCES = 20


def company_alias_tokens(person: dict, aliases: list[str]) -> set[str]:
    """Single-word aliases that are a bare PART of a multi-word alias and are
    not part of the person's name. Those are the company fragments."""
    namewords = {w.lower() for w in person.get("name", "").replace("-", " ").split()}
    single = [a for a in aliases if " " not in a and len(a) > 2]
    multi = [a for a in aliases if " " in a]
    return {a for a in single
            if any(a == w for m in multi for w in m.split())
            and a.lower() not in namewords}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the frozen list")
    ap.add_argument("--show", action="store_true", help="print the full distribution")
    args = ap.parse_args()

    roster = json.loads((ROOT / "data/roster/final.json").read_text())
    key = [k for k, v in roster.items() if isinstance(v, list)][0]
    people = {p["slug"]: p for p in roster[key]}
    aliases = json.loads((ROOT / "data/sources/aliases.json").read_text())
    dic = load_dictionary()

    open_root = ROOT / "data/transcripts_open"
    corpus: dict[str, list[str]] = {}
    for d in sorted(open_root.iterdir()):
        if d.is_dir():
            corpus[d.name] = [json.loads(f.read_text()).get("text") or ""
                              for f in sorted(d.glob("*.json"))]
    if not corpus:
        raise SystemExit(f"no transcripts under {open_root}; cannot measure spread")

    candidates: dict[str, set[str]] = {}
    for slug, toks in aliases.items():
        for t in company_alias_tokens(people.get(slug, {}), toks):
            candidates.setdefault(t, set()).add(slug)

    rows = []
    for token, owners in sorted(candidates.items()):
        pat = re.compile(r"\b" + re.escape(token.lower()) + r"(?:'s|s')?\b")
        own = other = 0
        for slug, texts in corpus.items():
            n = sum(len(pat.findall(t)) for t in texts)
            if slug in owners:
                own += n
            else:
                other += n
        total = own + other
        spread = (other / total) if total else 0.0
        how = in_dictionary(token, dic)
        ordinary = (bool(how) and spread >= SPREAD_THRESHOLD
                    and total >= MIN_OCCURRENCES)
        rows.append({
            "token": token, "owners": sorted(owners),
            "dictionary": how, "lower_own": own, "lower_other": other,
            "spread_outside_owner": round(spread, 4),
            "ordinary": ordinary,
        })

    rows.sort(key=lambda r: (-r["spread_outside_owner"], r["token"]))

    if args.show or not args.write:
        print(f"{'token':16}{'dict':10}{'own':>7}{'other':>8}{'spread':>9}  ordinary")
        for r in rows:
            if r["lower_own"] + r["lower_other"] == 0:
                continue
            print(f"  {r['token']:14}{str(r['dictionary'] or '-'):10}"
                  f"{r['lower_own']:>7}{r['lower_other']:>8}"
                  f"{r['spread_outside_owner']:>9.2f}  {'YES' if r['ordinary'] else ''}")
        n_ord = sum(1 for r in rows if r["ordinary"])
        print(f"\n{len(rows)} candidate tokens, {n_ord} ordinary "
              f"(dictionary AND spread >= {SPREAD_THRESHOLD})")

    if args.write:
        payload = {
            "generated_by": "scripts/build_blind_wordlist.py",
            "spread_threshold": SPREAD_THRESHOLD,
            "min_occurrences": MIN_OCCURRENCES,
            "transcripts_measured": sum(len(v) for v in corpus.values()),
            "leaders_measured": len(corpus),
            "rule": ("a token is ordinary only if it is in the system dictionary "
                     "(plurals stripped) AND at least spread_threshold of its "
                     "lowercase uses fall outside the leader who owns the alias, "
                     "over at least min_occurrences lowercase uses. An ordinary "
                     "token is still redacted where it is capitalised."),
            "ordinary": sorted(r["token"].lower() for r in rows if r["ordinary"]),
            "evidence": rows,
        }
        OUT.write_text(json.dumps(payload, indent=1) + "\n")
        print(f"wrote {OUT.relative_to(ROOT)}: "
              f"{len(payload['ordinary'])} ordinary tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
