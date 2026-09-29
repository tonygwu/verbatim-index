#!/usr/bin/env python3
"""A few words per person per year, for the year-square popover on the predictions page.

    .venv/bin/python scripts/year_summaries.py                    # dry run: what is missing or stale
    .venv/bin/python scripts/year_summaries.py --write            # one Fable call per person with work

WHAT IT IS FOR. Each square in a person's row counts the predictions they made in
one year. The popover used to name the colour band ("lightest blue: 1"), which
told a reader nothing the square did not. Operator request, 2026-09-29: say in a
few words what the person predicted that year instead.

A SUMMARY IS BOUND TO ITS INPUTS. Each entry carries `inputs_sha256`, a digest of
the prediction ids and claim texts in that cell. When a cell gains or loses a
prediction, or a claim is re-extracted under a corrected statement date, the
digest changes and the entry is stale. `build_predictions_site.py` refuses a page
whose cells lack a current summary rather than showing an old one, because a
summary of the wrong predictions is worse than none. Regenerating spends one
Fable call per person with stale cells, never per cell.

The year of a cell is the year of `source.statement_date`, exactly as
`build_predictions_site.statement_years` counts it. An undated prediction sits in
no year and gets no summary.

The output is a model's words, so this file is not a derived file: nothing
regenerates it implicitly, and `data_sync.py push` treats it as a shared path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
SUMMARIES_FILE = Path("predictions") / "year_summaries.json"
SCHEMA_VERSION = 1
#: What the model is ASKED for, and what the checker ACCEPTS. The checker keeps a
#: little slack over the ask, so a label one word over is not a failed call. The
#: first live run stated only the word cap and 32 of 53 people failed on length.
PROMPT_WORDS, PROMPT_CHARS = 8, 60
MAX_WORDS, MAX_CHARS = 10, 70
#: A summary describes what was PREDICTED. It must not grade it, or the popover
#: would state an outcome the page's own resolution does not back.
OUTCOME_WORDS = ("came true", "correct", "wrong", "failed", "missed", "right about", "accurate")


class SummaryError(Exception):
    pass


def year_of(rec: dict) -> str | None:
    d = rec["source"]["statement_date"]
    if not d:
        return None
    return str(dt.datetime.strptime(d[:10], "%Y-%m-%d").year)


def cells(by_slug: dict[str, list[dict]]) -> dict[str, dict[str, list[dict]]]:
    """{slug: {year: [records]}} over dated accepted records."""
    out: dict[str, dict[str, list[dict]]] = {}
    for slug, recs in by_slug.items():
        for r in recs:
            y = year_of(r)
            if y is None:
                continue
            out.setdefault(slug, {}).setdefault(y, []).append(r)
    return out


def cell_digest(recs: list[dict]) -> str:
    lines = sorted(f"{r['prediction_id']}\t{r['prediction']['normalized_claim']}" for r in recs)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def key(slug: str, year: str) -> str:
    return f"{slug}/{year}"


def load(path: Path) -> dict:
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("entries"), dict):
        raise SummaryError(f"{path}: expected {{\"schema_version\": {SCHEMA_VERSION}, \"entries\": {{...}}}}")
    return doc


def stale_cells(by_slug: dict[str, list[dict]], doc: dict) -> dict[str, list[str]]:
    """{slug: [years]} whose summary is missing or was written for different predictions."""
    out: dict[str, list[str]] = {}
    for slug, ys in cells(by_slug).items():
        for y, recs in ys.items():
            e = doc["entries"].get(key(slug, y))
            if e is None or e.get("inputs_sha256") != cell_digest(recs):
                out.setdefault(slug, []).append(y)
    return {s: sorted(v) for s, v in sorted(out.items())}


def summaries_for_page(by_slug: dict[str, list[dict]], path: Path) -> dict[str, dict[str, str]]:
    """{slug: {year: summary}} for every dated cell, or raise naming what is missing.

    The render's single entry point. Nothing is defaulted: a cell with no current
    summary stops the build, and the message names the command that fixes it.
    """
    path = Path(path)
    if not path.is_file():
        raise SummaryError(f"{path} is missing; run: .venv/bin/python scripts/year_summaries.py --write")
    doc = load(path)
    stale = stale_cells(by_slug, doc)
    if stale:
        n = sum(len(v) for v in stale.values())
        sample = ", ".join(f"{s} {','.join(v)}" for s, v in list(stale.items())[:5])
        raise SummaryError(f"{n} year cell(s) across {len(stale)} people have no current summary "
                           f"(e.g. {sample}); run: .venv/bin/python scripts/year_summaries.py --write")
    out: dict[str, dict[str, str]] = {}
    for slug, ys in cells(by_slug).items():
        out[slug] = {y: doc["entries"][key(slug, y)]["summary"] for y in ys}
    return out


PROMPT = """You are writing hover labels for a chart of public predictions made by {name}.
For EACH year below, write a label of at most {max_words} words and {max_chars} characters saying what {name}
predicted in that year. Name the subject concretely (the company, product,
technology or market). Plain words, no dates, no quotation marks, no ending
period. Describe only what was predicted: never say or hint whether it came true.
When a year holds several predictions, name the common thread or the two most
concrete ones.

{years}

Answer with one JSON object and nothing else, mapping each year to its label:
{{"YYYY": "label", ...}}
"""


def build_prompt(name: str, ys: dict[str, list[dict]]) -> str:
    blocks = []
    for y in sorted(ys):
        claims = "\n".join(f"  - {r['prediction']['normalized_claim']}" for r in ys[y])
        blocks.append(f"{y}:\n{claims}")
    return PROMPT.format(name=name, max_words=PROMPT_WORDS, max_chars=PROMPT_CHARS, years="\n".join(blocks))


def check_answer(obj, years: list[str]) -> list[str]:
    if not isinstance(obj, dict):
        return [f"answer is {type(obj).__name__}, not an object"]
    errs = []
    if set(obj) != set(years):
        errs.append(f"years {sorted(obj)} != asked {years}")
    for y, s in obj.items():
        if not isinstance(s, str) or not s.strip():
            errs.append(f"{y}: empty")
            continue
        if len(s.split()) > MAX_WORDS or len(s) > MAX_CHARS:
            errs.append(f"{y}: {len(s.split())} words / {len(s)} chars: {s!r}")
        low = s.lower()
        hit = [w for w in OUTCOME_WORDS if w in low]
        if hit:
            errs.append(f"{y}: grades the outcome ({hit}): {s!r}")
    return errs


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    import build_predictions_site as B  # noqa: E402  (imports the page's own record loader)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(REPO / "data"))
    ap.add_argument("--write", action="store_true", help="call the model for stale cells and write the file")
    ap.add_argument("--only", default="", help="comma-separated slugs")
    ap.add_argument("--fable-account", default="default",
                    help="a Claude config dir name under $HOME, or 'default' for ~/.claude")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    data = Path(args.data)
    path = data / SUMMARIES_FILE
    doc = load(path) if path.is_file() else {"schema_version": SCHEMA_VERSION, "entries": {}}
    loaded = B.load_records(data / "predictions")
    by_slug: dict[str, list[dict]] = {}
    for r in loaded["accepted"]:
        by_slug.setdefault(r["leader_slug"], []).append(r)
    names = {p["slug"]: p["name"] for p in json.loads((data / "roster" / "final.json").read_text())["roster"]}
    stale = stale_cells(by_slug, doc)
    only = {s for s in args.only.split(",") if s}
    if only:
        stale = {s: v for s, v in stale.items() if s in only}
    n_cells = sum(len(v) for v in stale.values())
    print(f"stale or missing: {n_cells} cells across {len(stale)} people")
    if not args.write or not stale:
        return 0

    from grade import call_fable  # noqa: E402  (imported late: dry runs need no harness)
    account = "__DEFAULT__" if args.fable_account == "default" else str(Path.home() / args.fable_account)
    run_id = f"{utc_now()}-year-summaries"
    all_cells = cells(by_slug)
    attempted = succeeded = 0
    taxonomy: dict[str, int] = {}
    for slug, years in stale.items():
        attempted += 1
        ys = {y: all_cells[slug][y] for y in years}
        prompt = build_prompt(names[slug], ys)
        try:
            text, tel = call_fable(prompt, account, args.timeout, workdir=str(Path("/tmp") / "year-summaries-jail"))
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end < start:
                raise SummaryError(f"no_json_in_response: {text[:200]!r}")
            obj = json.loads(text[start:end + 1])
            errs = check_answer(obj, years)
            if errs:
                raise SummaryError(f"rule_violation: {'; '.join(errs[:4])}")
        except Exception as exc:  # noqa: BLE001  (every failure is named and counted, never swallowed)
            etype = str(exc).split(":", 1)[0][:40] or type(exc).__name__
            taxonomy[etype] = taxonomy.get(etype, 0) + 1
            print(f"FAILED {slug}: {str(exc)[:300]}", file=sys.stderr)
            continue
        for y in years:
            doc["entries"][key(slug, y)] = {
                "summary": obj[y].strip(), "inputs_sha256": cell_digest(ys[y]), "n": len(ys[y]),
                "served_model": tel["judge_model"], "run_id": run_id, "generated_at_utc": utc_now()}
        succeeded += 1
        # Written after every person, so a quota wall costs progress, not the run.
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"ok {slug}: {len(years)} cells")
    print(f"people attempted {attempted}, succeeded {succeeded}, failed {attempted - succeeded}; "
          f"error_taxonomy {json.dumps(taxonomy)}")
    return 0 if succeeded == attempted else 1


if __name__ == "__main__":
    raise SystemExit(main())
