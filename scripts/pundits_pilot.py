#!/usr/bin/env python3
"""P6 discovery pilot: sample candidates, pre-check speakers, select by the P5 rules, and report yield and the gate.

Pundits plan, P6. Discovery proves who UPLOADED a video, not who SPEAKS in it.
The pilot therefore measures, per person, how many sampled candidates survive
to verified, selectable recordings. The full run sizes its candidate lists
from that yield. Four steps, each a subcommand:

  sample     seeded random draw of N discovered candidates per person, written
             as a fetch manifest (sources_to_manifest row shape plus the
             discovery stratum and channel id)
  precheck   automatic checks on fetched records. A FAIL is certain from the
             record alone: upload date missing, outside the window, or after
             an archival subject's last recording, or a substitute host named
             in the opening. Everything else is NEEDS_HUMAN, because the plan
             requires a person to check every pilot recording. Writes a
             checklist with blank fields for that person to fill.
  report     joins human labels, selects every verified recording, and returns
             the P6 gate: PASS, FAIL or INCONCLUSIVE, with per-person yield,
             a 95% interval and the one-sided 80% lower bound the plan uses.

No selection caps (operator, 2026-09-15, option b): every verified recording is
selected, and each person's venue mix is reported so format can be adjusted or
disclosed. Dates come from `yt_upload_date` and are never guessed.

  pundits_pilot.py sample   --discovered data-pundits/sources/pilot_discovered.json --n 24 --seed 20260914 --manifest data-pundits/sources/pilot_manifest.jsonl
  pundits_pilot.py precheck --manifest ... --transcripts data-pundits/transcripts --roster data-pundits/roster/final.json --out data-pundits/logs/pilot/precheck.json --checklist data-pundits/logs/pilot/human_checklist.json
  pundits_pilot.py report   --manifest ... --precheck ... --human data-pundits/logs/pilot/human_labels.json --roster ... --out data-pundits/logs/pilot/report.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

WINDOW = ("20210913", "20260913")
ARCHIVAL_YEARS = 5
OPENING_FRACTION = 0.15
TARGET = 12
MIN_VERIFIED_FOR_GATE = 4
VENUES = ("own_show_monologue", "reaction_stream", "debate", "guest_interview", "hosted_interview",
          "panel_show", "tv_segment", "speech_or_lecture", "other")
OWN_SHOW_VENUES = {"own_show_monologue", "reaction_stream"}
INTERLOCUTOR_VENUES = {"debate", "guest_interview", "hosted_interview", "panel_show", "tv_segment"}
# No main_speaker (operator, 2026-09-15): people, Fable and Sonnet could not apply it
# consistently. subject_present means "enough of the subject to be worth grading",
# and the judges' pooled subject-share estimate filters recordings with too little.
HUMAN_FIELDS = ("subject_present", "venue", "political_content", "checked_by")


# ---- binomial intervals (exact, no scipy) --------------------------------------------------------

def _tail_ge(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _bisect(f, lo: float = 0.0, hi: float = 1.0) -> float:
    for _ in range(100):
        mid = (lo + hi) / 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def lower_bound(k: int, n: int, alpha: float) -> float:
    """One-sided exact lower bound: the p at which P(X >= k) = alpha."""
    if k == 0:
        return 0.0
    return _bisect(lambda p: _tail_ge(k, n, p) >= alpha)


def upper_bound(k: int, n: int, alpha: float) -> float:
    if k == n:
        return 1.0
    return _bisect(lambda p: 1 - _tail_ge(k + 1, n, p) <= alpha)


def clopper_pearson(k: int, n: int) -> list[float]:
    return [round(lower_bound(k, n, 0.025), 4), round(upper_bound(k, n, 0.025), 4)]


# ---- sample --------------------------------------------------------------------------------------

def sample(discovered: dict, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for led in sorted(discovered["leaders"], key=lambda r: r["leader_slug"]):
        pool = sorted(led["sources"], key=lambda s: s["video_id"])
        rng.shuffle(pool)
        # Other-channel candidates are scarce (25 of 6,868 in the first pilot
        # discovery) and are the main source of interlocutor recordings, so they
        # take up to half the draw before own-channel uploads fill the rest.
        ext = [s for s in pool if s["discovery_stratum"] != "own_channel"]
        own = [s for s in pool if s["discovery_stratum"] == "own_channel"]
        picked = ext[: n // 2]
        picked += own[: n - len(picked)]
        picked += ext[n // 2: n // 2 + (n - len(picked))]
        for rank, s in enumerate(picked, 1):
            rows.append({"leader_slug": led["leader_slug"], "source_id": s["source_id"], "video_id": s["video_id"],
                         "title": s["title"], "venue": s["venue"], "kind": s["kind"], "year": 0, "rank": rank,
                         "channel_id": s.get("channel_id", ""), "discovery_stratum": s["discovery_stratum"]})
    return rows


# ---- precheck ------------------------------------------------------------------------------------

def window_for(person: dict) -> tuple[str, str]:
    if person.get("archival"):
        last = date.fromisoformat(person["last_recording_date"])
        start = last.replace(year=last.year - ARCHIVAL_YEARS)
        return start.strftime("%Y%m%d"), last.strftime("%Y%m%d")
    return WINDOW


def name_forms(person: dict) -> list[str]:
    parts = person["name"].split()
    forms = [person["name"], parts[0], parts[-1]] + list(person.get("handles") or [])
    return [f for f in dict.fromkeys(forms) if len(f) >= 3]


def precheck(rec: dict, person: dict) -> tuple[str, list[str]]:
    upload = str(rec.get("yt_upload_date") or "")
    if not re.fullmatch(r"\d{8}", upload):
        return "FAIL", ["upload date unknown; the window cannot be applied and is never guessed"]
    lo, hi = window_for(person)
    if upload > hi and person.get("archival"):
        return "FAIL", [f"uploaded {upload}, after the subject's last recording {hi}"]
    if not lo <= upload <= hi:
        return "FAIL", [f"uploaded {upload}, outside the window {lo}-{hi}"]
    words = (rec.get("text") or "").split()
    opening = " ".join(words[: max(1, int(len(words) * OPENING_FRACTION))])
    forms = "|".join(re.escape(f) for f in sorted(name_forms(person), key=len, reverse=True))
    sub = re.search(r"\b(filling in for|sitting in for|in for|guest[- ]hosting for|subbing for)\s+"
                    r"(?:my (?:friend|colleague|buddy)\s+)?(" + forms + r")\b", opening, re.I)
    if sub:
        return "FAIL", [f"substitute host: '{sub.group(0)}' in the opening"]
    away = re.search(r"\b(" + forms + r")\s+is\s+(away|out|off|on vacation|on leave)\b", opening, re.I)
    if away:
        return "FAIL", [f"substitute host: '{away.group(0)}' in the opening"]
    reasons = ["passes automatic checks; a person must confirm the subject is present and the main speaker"]
    text = rec.get("text") or ""
    if not any(re.search(r"\b" + re.escape(f) + r"\b", text, re.I) for f in name_forms(person)):
        reasons.append("the subject is never named in the transcript; check for a guest-only episode")
    return "NEEDS_HUMAN", reasons


# ---- report --------------------------------------------------------------------------------------

def human_errors(label: dict) -> list[str]:
    errs = [f"missing `{f}`" for f in HUMAN_FIELDS if f not in label or label[f] in (None, "")]
    if not errs:
        if not all(isinstance(label[f], bool) for f in ("subject_present", "political_content")):
            errs.append("subject_present and political_content must be true or false")
        if label["venue"] not in VENUES:
            errs.append(f"venue `{label['venue']}` is not one of {list(VENUES)}")
    return errs


def select(verified: list[dict], seed: int) -> list[dict]:
    """Every verified recording, in a seeded order.

    The P5 venue, channel, 7-day and count caps were dropped with the operator on
    2026-09-15 (option b). On the pilot, 5 of 10 people could not reach 4
    recordings with an interlocutor, and Asmongold would have kept 4 of 24.
    Format is handled by the reported venue mix and the supported venue
    adjustment instead; equal format weighting (option c) is the fallback.
    """
    rng = random.Random(seed)
    pool = sorted(verified, key=lambda r: r["key"])
    rng.shuffle(pool)
    return pool


def report(manifest: list[dict], prechecks: dict, human: dict, roster: dict, seed: int) -> dict:
    people: dict[str, dict] = {}
    pending, invalid, wrong_person = [], [], []
    by_person = defaultdict(list)
    for row in manifest:
        by_person[row["leader_slug"]].append(row)
    for slug, rows in sorted(by_person.items()):
        person = roster[slug]
        own_ids = {c["channel_id"] for c in person.get("own_channels") or []}
        tally: Counter = Counter()
        drafted = 0
        verified = []
        strata: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            key = f"{slug}/{row['source_id']}"
            strata[row["discovery_stratum"]]["sampled"] += 1
            pc = prechecks.get(key)
            if pc is None:
                tally["not_fetched"] += 1
                continue
            if pc["verdict"] == "FAIL":
                tally["precheck_fail"] += 1
                continue
            label = human.get(key)
            if label is None:
                pending.append(key)
                tally["awaiting_human"] += 1
                continue
            errs = human_errors(label)
            if errs:
                invalid.append({"key": key, "errors": errs})
                tally["invalid_label"] += 1
                continue
            if not label["subject_present"]:
                wrong_person.append(key)
                tally["wrong_person"] += 1
                continue
            if not label["political_content"]:
                # Operator decision 2026-09-15: no political content (for example a
                # gaming stream) is excluded, and counted as its own outcome.
                tally["off_topic"] += 1
                continue
            tally["verified"] += 1
            if label.get("drafted_by_model"):
                drafted += 1
            strata[row["discovery_stratum"]]["verified"] += 1
            verified.append({"key": key, "venue": label["venue"], "channel_id": row["channel_id"], "upload": pc["upload"]})
        chosen = select(verified, seed)
        # Yield is per ATTEMPT. Rows the fetch never reached (it stops at a per-person
        # target) are not attempts; dividing by all sampled rows made every live pilot
        # yield read about a third of its true value (2026-09-15).
        k, n = tally["verified"], len(rows) - tally["not_fetched"]
        people[slug] = {
            "sampled": len(rows), "attempted": n, "outcomes": dict(tally), "verified": k, "verified_model_drafted": drafted,
            "by_discovery_stratum": {s: {"sampled": c["sampled"], "verified": c["verified"],
                                         "yield_ci95": clopper_pearson(c["verified"], c["sampled"])}
                                     for s, c in sorted(strata.items())},
            "selected_keys": [c["key"] for c in chosen],
            "venue_mix": dict(sorted(Counter(c["venue"] for c in chosen).items())),
            "yield": round(k / n, 4) if n else None, "yield_ci95": clopper_pearson(k, n) if n else None,
            "yield_lower80": round(lower_bound(k, n, 0.20), 4) if n else None,
            "selected": len(chosen),
            "selected_interlocutor": sum(c["venue"] in INTERLOCUTOR_VENUES for c in chosen),
            "selected_own_show": sum(c["venue"] in OWN_SHOW_VENUES for c in chosen),
            "candidates_needed_full_run": (max(24, math.ceil(TARGET / lower_bound(k, n, 0.20)))
                                           if n and k else None),
        }
    if pending or invalid:
        verdict, why = "INCONCLUSIVE", (f"{len(pending)} recordings await human verification and "
                                        f"{len(invalid)} labels are invalid")
    elif any(p["selected"] < MIN_VERIFIED_FOR_GATE for p in people.values()):
        short = sorted(s for s, p in people.items() if p["selected"] < MIN_VERIFIED_FOR_GATE)
        verdict, why = "FAIL", f"fewer than {MIN_VERIFIED_FOR_GATE} verified, selectable recordings for {short}"
    else:
        verdict, why = "PASS", "every pilot person has enough verified recordings; wrong-person records are excluded"
    return {"gate": verdict, "why": why, "people": people, "wrong_person_found": wrong_person,
            "model_drafted_verified": sum(p["verified_model_drafted"] for p in people.values()),
            "pending": pending, "invalid_labels": invalid,
            "limits": "no venue, channel, 7-day or count caps (operator, 2026-09-15); every verified recording is "
                      "selected and each person's venue_mix is reported; the P6 gate counts selected recordings"}


def main() -> int:
    import study_profile as SP
    from atomicio import write_atomic
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--discovered", required=True)
    s.add_argument("--n", type=int, default=24)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--manifest", required=True)
    p = sub.add_parser("precheck")
    p.add_argument("--manifest", required=True)
    p.add_argument("--transcripts", required=True)
    p.add_argument("--roster", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--checklist", required=True)
    r = sub.add_parser("report")
    for a in ("--manifest", "--precheck", "--human", "--roster", "--out"):
        r.add_argument(a, required=True)
    r.add_argument("--seed", type=int, default=20260914)
    for x in (s, p, r):
        SP.add_study_arg(x)
    args = ap.parse_args()

    if args.cmd == "sample":
        SP.guard(args.study, args.discovered, args.manifest)
        rows = sample(json.loads(Path(args.discovered).read_text()), args.n, args.seed)
        write_atomic(Path(args.manifest), "".join(json.dumps(x) + "\n" for x in rows))
        print(json.dumps({"rows": len(rows), "per_person": dict(Counter(x["leader_slug"] for x in rows)),
                          "by_stratum": dict(Counter(x["discovery_stratum"] for x in rows))}, indent=1))
        return 0

    roster = {x["slug"]: x for x in json.loads(Path(args.roster).read_text())["roster"]}
    manifest = [json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    if args.cmd == "precheck":
        SP.guard(args.study, args.manifest, args.transcripts, args.roster, args.out, args.checklist)
        results, checklist = {}, {}
        for row in manifest:
            path = Path(args.transcripts) / row["leader_slug"] / f"{row['source_id']}.json"
            if not path.exists():
                continue
            rec = json.loads(path.read_text())
            verdict, reasons = precheck(rec, roster[row["leader_slug"]])
            key = f"{row['leader_slug']}/{row['source_id']}"
            results[key] = {"verdict": verdict, "reasons": reasons, "upload": rec.get("yt_upload_date")}
            if verdict == "NEEDS_HUMAN":
                checklist[key] = {"url": f"https://www.youtube.com/watch?v={row['video_id']}", "title": row["title"],
                                  "channel": row["venue"], "upload": rec.get("yt_upload_date"), "hints": reasons,
                                  "subject_present": None, "venue": None, "political_content": None, "checked_by": None,
                                  "notes": ""}
        write_atomic(Path(args.out), json.dumps(results, indent=1))
        write_atomic(Path(args.checklist), json.dumps(checklist, indent=1, ensure_ascii=False))
        print(json.dumps({"manifest_rows": len(manifest), "fetched": len(results),
                          "verdicts": dict(Counter(v["verdict"] for v in results.values())),
                          "fail_reasons": dict(Counter(v["reasons"][0].split(";")[0].split(":")[0]
                                                       for v in results.values() if v["verdict"] == "FAIL"))}, indent=1))
        return 0

    SP.guard(args.study, args.manifest, args.precheck, args.human, args.roster, args.out)
    human = json.loads(Path(args.human).read_text()) if Path(args.human).exists() else {}
    out = report(manifest, json.loads(Path(args.precheck).read_text()), human, roster, args.seed)
    write_atomic(Path(args.out), json.dumps(out, indent=1))
    print(json.dumps({"gate": out["gate"], "why": out["why"]}, indent=1))
    return 0 if out["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
