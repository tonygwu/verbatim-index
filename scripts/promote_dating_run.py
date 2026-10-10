#!/usr/bin/env python3
"""Copy a dating run's confirmed dates into the production date files.

The dating stage (date_recordings.py) writes its confirmed dates into the RUN's own
overrides.json and checks.json, never production's (rescue round 4, critique 3 A5).
This is the one step that moves them: every entry of the run is added to
predictions/statement_date_overrides.json or predictions/statement_date_checks.json
under the data root.

Additive and fail-loud. An entry already in production with the same content is
reported as unchanged. An entry whose transcript production already dates
differently, in either file, stops the promotion before anything is written and is
named: production's entry may be the operator's own (the Andreessen override), and
choosing between two dates is a person's call, not this script's. Production entries
the run does not mention are kept and counted.

Rule R1 across runs (--against, repeatable). A run with one dater, such as the
Astra run over another run's queue, never saw the other daters' proposals, so its
merge could not apply R1. With --against, an entry is HELD BACK, and named, when a
proposal in another run passed every rule before the source checks
(dating_lib.assess, eligible) and its range does not contain the entry's date. That
is the merge's own R1, applied across runs. A held entry stays in its run's file
for a person; it is never promoted and never silently dropped. A proposal from a dater
that had no web tools (dating_lib.NO_WEB_DATERS: Fable before 2026-10-05, which answered
from memory) holds nothing back (operator, 2026-10-09, ledger VD-17 option B), and each one
skipped is reported, so the skip is never silent.

--hold-file holds named entries for a person's review the same way: reported HELD, never
promoted, left in the run's file.

Both merged files are loaded back through the production loaders, which re-verify
every agent entry from its run's stored proposals, before either file is replaced.
Dry run by default; --apply writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dating_lib as DL  # noqa: E402
from date_recordings import HARNESSES  # noqa: E402
import predictions_lib as L  # noqa: E402

PRODUCTION_NOTES = {
    "overrides": ("Reviewed statement-date overrides. Operator entries are taken on the operator's word; every "
                  "agent entry re-verifies on load from the dating run it names. Promoted runs: {runs}."),
    "checks": ("Dating checks that confirm a transcript's own upload or publication date. Every agent entry "
               "re-verifies on load from the dating run it names. Promoted runs: {runs}."),
}


def _read(path: Path, key: str) -> dict:
    if not path.exists():
        return {"schema_version": 1, "notes": "", key: {}}
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or not isinstance(doc.get(key), dict):
        raise SystemExit(f"{path} has no {key!r} object")
    return doc


def _runs_named(entries: dict) -> list[str]:
    return sorted({(e.get("confirmation") or {}).get("run") for e in entries.values()} - {None})


def _transcript(tid: str, roots: list[Path]) -> dict:
    slug, sid = tid.split("/", 1)
    for r in roots:
        if (r / slug / f"{sid}.json").is_file():
            return json.loads((r / slug / f"{sid}.json").read_text())
    raise SystemExit(f"{tid}: no transcript under {[str(r) for r in roots]}")


def r1_against(tid: str, day: str, rec: dict, others: list[Path], skipped: list[str] | None = None) -> list[str]:
    """Every eligible proposal in another run whose range does not contain `day` (rule R1 across runs).

    A proposal from a dater with no web tools is not read; it is appended to `skipped` instead.
    """
    slug, sid = tid.split("/", 1)
    out = []
    for run in others:
        for h in HARNESSES:
            f = run / "proposals" / slug / f"{sid}.{h}.json"
            if not f.is_file():
                continue
            if h in DL.NO_WEB_DATERS:
                if skipped is not None:
                    skipped.append(f"{run.name} {h} {tid}")
                continue
            a = DL.assess(rec, json.loads(f.read_text()), [])
            if not a["eligible"]:
                continue
            e, lat = a["prop"]["speech_date_earliest"], a["prop"]["speech_date_latest"]
            if not e <= day <= lat:
                out.append(f"{run.name} {h} named {e}..{lat}")
    return out


def plan(run_dir: Path, data: Path, against: list[Path] | None = None, hold: dict | None = None) -> dict:
    """What a promotion would do, or SystemExit naming every conflict. Writes nothing."""
    roots = [data / d for d in L.TRANSCRIPT_DIRS]
    run = {"overrides": L.load_statement_date_overrides(run_dir / "overrides.json", roots),
           "checks": L.load_statement_date_checks(run_dir / "checks.json", roots)}
    paths = {"overrides": data / L.DATE_OVERRIDES_FILE, "checks": data / L.DATE_CHECKS_FILE}
    prod = {k: _read(p, k) for k, p in paths.items()}
    hold = hold or {}
    unknown = sorted(set(hold) - set(run["overrides"]) - set(run["checks"]))
    if unknown:
        raise SystemExit(f"--hold-file names {unknown}, which this run does not date; nothing written")
    both = set(run["overrides"]) & set(run["checks"])
    if both:
        raise SystemExit(f"the run dates {sorted(both)} in both its overrides and its checks; one date source per "
                         f"transcript")
    conflicts, added, unchanged = [], {"overrides": [], "checks": []}, {"overrides": [], "checks": []}
    held, skipped = {}, []
    for kind, other in (("overrides", "checks"), ("checks", "overrides")):
        for tid, e in run[kind].items():
            if tid in hold:
                held[tid] = f"{kind[:-1]} {e['statement_date']}: held for review: {hold[tid]}"
                continue
            why = r1_against(tid, e["statement_date"], _transcript(tid, roots), against or [], skipped)
            if why:
                held[tid] = f"{kind[:-1]} {e['statement_date']}: " + "; ".join(why)
                continue
            if tid in prod[other][other]:
                conflicts.append(f"{tid}: the run has a{'n override' if kind == 'overrides' else ' check'}, but "
                                 f"production's {other} file already dates it")
            elif tid not in prod[kind][kind]:
                added[kind].append(tid)
            elif prod[kind][kind][tid] == e:
                unchanged[kind].append(tid)
            else:
                old = prod[kind][kind][tid]
                conflicts.append(f"{tid}: production's {kind} entry ({old.get('statement_date')}, confirmed_by "
                                 f"{old.get('confirmed_by')}) differs from the run's ({e.get('statement_date')}, "
                                 f"confirmed_by {e.get('confirmed_by')})")
    if conflicts:
        raise SystemExit(f"refused: {len(conflicts)} conflict(s) with production; nothing written\n  "
                         + "\n  ".join(conflicts))
    merged = {}
    for kind in ("overrides", "checks"):
        entries = dict(prod[kind][kind])
        for tid in added[kind]:
            entries[tid] = run[kind][tid]
        entries = dict(sorted(entries.items()))
        runs = ", ".join(_runs_named(entries)) or "none"
        merged[kind] = {"schema_version": 1, "notes": PRODUCTION_NOTES[kind].format(runs=runs), kind: entries}
    kept = {k: sorted(set(prod[k][k]) - set(run[k])) for k in prod}
    return {"paths": paths, "merged": merged, "added": added, "unchanged": unchanged, "kept": kept,
            "held": held, "skipped": skipped, "before": {k: len(prod[k][k]) for k in prod}}


def apply(p: dict, data: Path, guard_root: Path | None) -> None:
    """Write both files, each loaded back through the production loader first.

    guard_root is None for this clone's own data/, so the write passes the clone's
    full data-write guard; a test passes its temporary root.
    """
    roots = [data / d for d in L.TRANSCRIPT_DIRS]
    loaders = {"overrides": L.load_statement_date_overrides, "checks": L.load_statement_date_checks}
    for kind in ("overrides", "checks"):
        path = p["paths"][kind]
        tmp = path.with_name(f".{path.name}.promote-check")
        text = json.dumps(p["merged"][kind], indent=2, ensure_ascii=False) + "\n"
        tmp.write_text(text)
        try:
            got = loaders[kind](tmp, roots)
        finally:
            tmp.unlink()
        if len(got) != len(p["merged"][kind][kind]):
            raise SystemExit(f"{kind}: the loader read {len(got)} entries back, the merge holds "
                             f"{len(p['merged'][kind][kind])}")
        L.write_prediction_file(path, text, guard_root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True, help="a dating run holding overrides.json and checks.json")
    ap.add_argument("--data-root", type=Path, default=None, help="default: this clone's data/")
    ap.add_argument("--against", type=Path, action="append", default=[],
                    help="another dating run whose eligible proposals an entry must not contradict (rule R1)")
    ap.add_argument("--hold-file", type=Path, default=None,
                    help="a JSON object {transcript_id: reason}: entries a person holds for review, reported HELD and "
                         "never promoted (for example two-dater agreements when only source-checked dates may go)")
    ap.add_argument("--apply", action="store_true", help="write the production files; without it, report only")
    args = ap.parse_args(argv)
    data = (args.data_root or L.data_root()).resolve()
    run_dir = args.run_dir.resolve()
    for f in ("overrides.json", "checks.json"):
        if not (run_dir / f).is_file():
            raise SystemExit(f"{run_dir / f} does not exist")
    for o in args.against:
        if not (o / "proposals").is_dir():
            raise SystemExit(f"--against {o}: no proposals/ directory, so it is not a dating run")
    hold = json.loads(args.hold_file.read_text()) if args.hold_file else {}
    if not isinstance(hold, dict) or not all(isinstance(v, str) and v for v in hold.values()):
        raise SystemExit(f"--hold-file {args.hold_file}: want a JSON object of transcript id -> non-empty reason")
    p = plan(run_dir, data, [o.resolve() for o in args.against], hold)
    for kind in ("overrides", "checks"):
        print(f"{kind}: production {p['before'][kind]} -> {len(p['merged'][kind][kind])}; added "
              f"{len(p['added'][kind])}, unchanged {len(p['unchanged'][kind])}, production-only kept "
              f"{len(p['kept'][kind])}{' ' + str(p['kept'][kind]) if p['kept'][kind] else ''}")
    print(f"held back by rule R1 against {[str(o) for o in args.against]} or by --hold-file: {len(p['held'])}")
    for tid, why in sorted(p["held"].items()):
        print(f"  HELD {tid}: {why}")
    print(f"proposals rule R1 did not read, from daters with no web tools {list(DL.NO_WEB_DATERS)}: "
          f"{len(p['skipped'])}")
    for s in p["skipped"]:
        print(f"  not read (no web tools): {s}")
    if not args.apply:
        print("dry run: nothing written (pass --apply)")
        return 0
    apply(p, data, args.data_root and data)
    print(f"written: {p['paths']['overrides']}, {p['paths']['checks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
