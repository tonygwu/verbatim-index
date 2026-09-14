#!/usr/bin/env python3
"""Build the P7 labelling kit: attribution windows and the quote-audit frame, with nothing pre-labelled.

Pundits plan, P7. Both outputs are material for PEOPLE to label, following
docs/PUNDITS-LABELLING-GUIDE.md. Every label field is written empty. A format
whose recordings cannot supply its quota is reported as a shortfall and is
never topped up from another format, because that would silently change what
the gate measures.

  windows   30 ten-minute windows, 6 per format, cut on the transcript's own
            [hh:mm:ss] marks from recordings a person has verified (subject
            present, main speaker). The format is the HUMAN venue label, never a
            judge's. One window per recording, seeded.
  quotes    300 evidence quotes a judge attributed to the subject, 60 per
            format, balanced round-robin across (judge, mode). The judge's own
            speaker label and identity go only into a separate key file, so the
            person labelling cannot see them.

  pundits_label_kit.py windows --transcripts data-pundits/transcripts --human data-pundits/logs/pilot/human_labels.json \
      --seed 20260914 --out data-pundits/labels/windows
  pundits_label_kit.py quotes --grades data-pundits/grades --human data-pundits/logs/pilot/human_labels.json \
      --seed 20260914 --out data-pundits/labels/quotes
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from itertools import cycle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FORMATS = {
    "reaction": {"reaction_stream"},
    "debate": {"debate"},
    "panel": {"panel_show"},
    "interview": {"guest_interview", "hosted_interview"},
    "monologue": {"own_show_monologue"},
}
WINDOWS_PER_FORMAT = 6
WINDOW_SEC = 600
QUOTES_PER_FORMAT = 60
MARK = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")


def format_of(venue: str | None) -> str | None:
    return next((f for f, venues in FORMATS.items() if venue in venues), None)


def verified(human: dict) -> dict[str, str]:
    """key -> format, for recordings a person marked present and main speaker."""
    out = {}
    for key, lab in human.items():
        if lab.get("subject_present") is True and lab.get("main_speaker") is True and lab.get("checked_by"):
            f = format_of(lab.get("venue"))
            if f:
                out[key] = f
    return out


def marks(text: str) -> list[tuple[int, int]]:
    """(seconds, character offset) for every timestamp mark."""
    return [(int(h) * 3600 + int(m) * 60 + int(s), mt.start()) for mt in MARK.finditer(text)
            for h, m, s in [mt.groups()]]


def cut_window(text: str, rng: random.Random, length: int = WINDOW_SEC) -> dict | None:
    ms = marks(text)
    starts = [(t, off) for t, off in ms if any(t2 >= t + length for t2, _ in ms)]
    if not starts:
        return None
    t0, off0 = rng.choice(starts)
    t1, off1 = next((t, off) for t, off in ms if t >= t0 + length)
    body = text[off0:off1]
    return {"start_sec": t0, "end_sec": t1, "text": body, "words": body.split()}


def build_windows(transcripts: Path, human: dict, seed: int, per_format: int = WINDOWS_PER_FORMAT) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    by_format: dict[str, list[str]] = defaultdict(list)
    for key, f in sorted(verified(human).items()):
        by_format[f].append(key)
    windows, shortfall = [], {}
    for f in FORMATS:
        keys = by_format.get(f, [])
        rng.shuffle(keys)
        got = 0
        for key in keys:
            if got >= per_format:
                break
            slug, sid = key.split("/", 1)
            path = transcripts / slug / f"{sid}.json"
            if not path.exists():
                continue
            rec = json.loads(path.read_text())
            w = cut_window(rec.get("text") or "", rng)
            if w is None:
                continue
            got += 1
            windows.append({"window_id": f"{f}-{got:02d}", "format": f, "venue_label_by": human[key]["checked_by"],
                            "leader_slug": slug, "source_id": sid, "video_id": rec.get("video_id"),
                            "audio_url": f"https://www.youtube.com/watch?v={rec.get('video_id')}&t={w['start_sec']}s",
                            **w, "labels": {"annotator_a": None, "annotator_b": None, "adjudicator": None}})
        if got < per_format:
            shortfall[f] = {"wanted": per_format, "got": got, "verified_recordings": len(keys)}
    return windows, shortfall


def build_quotes(grades: Path, human: dict, seed: int, per_format: int = QUOTES_PER_FORMAT) -> tuple[list[dict], dict, dict]:
    rng = random.Random(seed)
    fmt = verified(human)
    cells: dict[str, dict[tuple[str, str], list[dict]]] = defaultdict(lambda: defaultdict(list))
    for path in sorted(grades.rglob("*.json")):
        if "_obsolete" in path.parts or "_provenance" in path.parts:
            continue
        rec = json.loads(path.read_text())
        key = f"{rec.get('leader_slug')}/{rec.get('source_id')}"
        f = fmt.get(key)
        g = rec.get("grade") or {}
        if f is None or not isinstance(g.get("dimensions"), dict):
            continue
        for dim, block in sorted(g["dimensions"].items()):
            for i, ev in enumerate((block or {}).get("evidence") or []):
                if ev.get("speaker") == "subject" and ev.get("quote"):
                    cells[f][(rec["judge"], rec["mode"])].append(
                        {"key": key, "grade_file": str(path.relative_to(grades)), "dimension": dim, "index": i,
                         "judge": rec["judge"], "mode": rec["mode"], "quote": ev["quote"],
                         "timestamp": ev.get("timestamp"), "video_id": rec.get("video_id")})
    to_label, answer_key, shortfall = [], {}, {}
    for f in FORMATS:
        pools = {c: rng.sample(v, len(v)) for c, v in sorted(cells[f].items())}
        taken = 0
        order = sorted(pools)
        while taken < per_format and any(pools.values()):
            for c in order:
                if taken >= per_format:
                    break
                if pools[c]:
                    q = pools[c].pop()
                    taken += 1
                    qid = f"{f}-{taken:03d}"
                    slug, sid = q["key"].split("/", 1)
                    to_label.append({"quote_id": qid, "format": f, "quote": q["quote"], "timestamp_hint": q["timestamp"],
                                     "leader_slug": slug, "source_id": sid,
                                     "audio_url": f"https://www.youtube.com/watch?v={q['video_id']}" if q["video_id"] else None,
                                     "spoken_by_subject": None, "checked_by": None, "notes": ""})
                    answer_key[qid] = {k: q[k] for k in ("grade_file", "dimension", "index", "judge", "mode")} | {
                        "judge_speaker": "subject"}
        if taken < per_format:
            shortfall[f] = {"wanted": per_format, "got": taken,
                            "available_by_cell": {f"{j}/{m}": len(v) for (j, m), v in sorted(cells[f].items())}}
    return to_label, answer_key, shortfall


def main() -> int:
    import study_profile as SP
    from atomicio import write_atomic
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("windows")
    w.add_argument("--transcripts", required=True)
    q = sub.add_parser("quotes")
    q.add_argument("--grades", required=True)
    for x in (w, q):
        x.add_argument("--human", required=True)
        x.add_argument("--seed", type=int, required=True)
        x.add_argument("--out", required=True)
        SP.add_study_arg(x)
    args = ap.parse_args()
    src = args.transcripts if args.cmd == "windows" else args.grades
    SP.guard(args.study, src, args.human, args.out)
    human = json.loads(Path(args.human).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "windows":
        windows, shortfall = build_windows(Path(args.transcripts), human, args.seed)
        for win in windows:
            write_atomic(out / f"{win['window_id']}.json", json.dumps(win, indent=1, ensure_ascii=False))
        summary = {"windows": len(windows), "by_format": dict(Counter(x["format"] for x in windows)), "shortfall": shortfall}
    else:
        to_label, key, shortfall = build_quotes(Path(args.grades), human, args.seed)
        write_atomic(out / "quotes_to_label.json", json.dumps(to_label, indent=1, ensure_ascii=False))
        write_atomic(out / "quotes_answer_key.json", json.dumps(key, indent=1))
        summary = {"quotes": len(to_label), "by_format": dict(Counter(x["format"] for x in to_label)), "shortfall": shortfall}
    write_atomic(out / "summary.json", json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 1 if shortfall else 0


if __name__ == "__main__":
    sys.exit(main())
