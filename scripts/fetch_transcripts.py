#!/usr/bin/env python3
"""Fetch verbatim transcripts for leader appearances from YouTube auto-captions.

Reads a source manifest (JSONL, one source per line) and writes one JSON
transcript file per source. Fails loud: every source ends up either in the
output directory or in the error report with a typed reason. Nothing is
silently skipped.

Manifest line schema (all fields required):
  {"leader_slug": "...", "source_id": "...", "video_id": "...",
   "title": "...", "venue": "...", "kind": "podcast|interview|keynote|fireside|panel",
   "year": 2025}

Usage:
  fetch_transcripts.py --manifest data/sources/all.jsonl --out data/transcripts \
      --errors data/logs/fetch_errors.jsonl [--workers 8] [--force]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("leader_slug", "source_id", "video_id", "title", "venue", "kind", "year")

# Error taxonomy. Every failure maps to exactly one of these.
E_NO_TRANSCRIPT = "no_transcript_available"
E_DISABLED = "transcripts_disabled"
E_UNAVAILABLE = "video_unavailable"
E_BLOCKED = "ip_blocked_or_ratelimited"
E_NOT_ENGLISH = "no_english_track"
E_TOO_SHORT = "below_min_words"
E_METADATA = "metadata_fetch_failed"
E_OTHER = "other"

_print_lock = threading.Lock()

# YouTube rate-limits caption requests hard, and returns IpBlocked or HTTP 429
# once it decides you have asked too often. A global minimum interval between
# caption requests keeps the whole run under that ceiling; without it a burst of
# parallel workers gets the IP throttled and every later request fails.
class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


RETRYABLE = {E_BLOCKED}
BACKOFF_SEC = [8, 30, 90]


def log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(exc: Exception) -> str:
    name = type(exc).__name__
    text = f"{name}: {exc}".lower()
    if "transcriptsdisabled" in name.lower() or "subtitles are disabled" in text:
        return E_DISABLED
    if "notranscriptfound" in name.lower() or "no transcripts were found" in text:
        return E_NO_TRANSCRIPT
    if "videounavailable" in name.lower() or "unavailable" in text or "private" in text:
        return E_UNAVAILABLE
    if ("ipblocked" in name.lower() or "too many requests" in text
            or "blocked" in text or "429" in text or "ratelimit" in name.lower()):
        return E_BLOCKED
    if "requestblocked" in name.lower() or "age" in text and "restrict" in text:
        return E_BLOCKED
    return E_OTHER


def fetch_metadata(video_id: str) -> dict:
    """Pull title, channel, duration, upload date and description via yt-dlp.

    Metadata failure is non-fatal: the transcript is still usable, we just
    record that the metadata is missing rather than inventing values.
    """
    try:
        proc = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--no-warnings",
                "--dump-single-json",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            return {"_meta_error": (proc.stderr or "").strip()[:400]}
        d = json.loads(proc.stdout)
        return {
            "yt_title": d.get("title"),
            "yt_channel": d.get("channel") or d.get("uploader"),
            "yt_duration_sec": d.get("duration"),
            "yt_upload_date": d.get("upload_date"),  # YYYYMMDD, YouTube's own field
            "yt_description": (d.get("description") or "")[:4000],
            "yt_view_count": d.get("view_count"),
        }
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort by design
        return {"_meta_error": f"{type(exc).__name__}: {exc}"[:400]}


def segments_to_text(segments: list[dict]) -> tuple[str, list[dict]]:
    """Flatten caption cues into readable text, keeping coarse timestamps.

    YouTube auto-captions arrive as short overlapping cues. We join them and
    emit a timestamp marker every ~60s so a judge can cite roughly where in
    the appearance a passage sits.
    """
    parts: list[str] = []
    marks: list[dict] = []
    next_mark = 0.0
    for seg in segments:
        start = float(seg.get("start", 0.0))
        txt = (seg.get("text") or "").replace("\n", " ").strip()
        if not txt:
            continue
        if start >= next_mark:
            mm, ss = divmod(int(start), 60)
            hh, mm = divmod(mm, 60)
            stamp = f"[{hh:02d}:{mm:02d}:{ss:02d}]"
            parts.append(f"\n{stamp} ")
            marks.append({"stamp": stamp, "start_sec": start, "char_offset": sum(len(p) for p in parts)})
            next_mark = start + 60.0
        parts.append(txt + " ")
    text = "".join(parts).strip()
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text, marks


def fetch_one(src: dict, out_dir: Path, min_words: int, force: bool) -> dict:
    slug = src["leader_slug"]
    sid = src["source_id"]
    vid = src["video_id"]
    dest = out_dir / slug / f"{sid}.json"

    if dest.exists() and not force:
        return {"status": "cached", "leader_slug": slug, "source_id": sid, "path": str(dest)}

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_OTHER, "detail": "youtube_transcript_api not importable"}

    try:
        api = YouTubeTranscriptApi()
        listing = api.list(vid)
        track = None
        track_kind = None
        # Prefer a human-made English track; fall back to auto-generated English.
        try:
            track = listing.find_manually_created_transcript(["en", "en-US", "en-GB"])
            track_kind = "manual"
        except Exception:
            try:
                track = listing.find_generated_transcript(["en", "en-US", "en-GB"])
                track_kind = "auto"
            except Exception:
                return {"status": "failed", "leader_slug": slug, "source_id": sid,
                        "error_type": E_NOT_ENGLISH,
                        "detail": "no English manual or generated track"}
        fetched = track.fetch()
        segments = [{"start": s.start, "duration": s.duration, "text": s.text}
                    for s in fetched]
    except Exception as exc:  # noqa: BLE001 - classified into the taxonomy above
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": classify(exc), "detail": f"{type(exc).__name__}: {exc}"[:400]}

    text, marks = segments_to_text(segments)
    words = len(text.split())
    if words < min_words:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_TOO_SHORT,
                "detail": f"{words} words < min {min_words}"}

    meta = fetch_metadata(vid)
    duration = meta.get("yt_duration_sec") or (segments[-1]["start"] + segments[-1]["duration"] if segments else None)

    record = {
        "leader_slug": slug,
        "source_id": sid,
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "declared_title": src["title"],
        "declared_venue": src["venue"],
        "declared_kind": src["kind"],
        "declared_year": src["year"],
        "caption_track": track_kind,
        "word_count": words,
        "char_count": len(text),
        "duration_sec": duration,
        "n_timestamp_marks": len(marks),
        "fetched_at_utc": utcnow(),
        "fetch_method": "youtube_transcript_api",
        **meta,
        "text": text,
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return {"status": "ok", "leader_slug": slug, "source_id": sid,
            "words": words, "track": track_kind, "path": str(dest)}


def fetch_with_retry(src: dict, out_dir: Path, min_words: int, force: bool,
                     limiter: RateLimiter) -> dict:
    """One source, retried only for throttling. Other failures move on immediately."""
    last = None
    for attempt, wait in enumerate([0] + BACKOFF_SEC):
        if wait:
            log(f"    throttled on {src['video_id']}, backing off {wait}s "
                f"(attempt {attempt + 1}/{len(BACKOFF_SEC) + 1})")
            time.sleep(wait)
        limiter.wait()
        r = fetch_one(src, out_dir, min_words, force)
        if r["status"] != "failed" or r.get("error_type") not in RETRYABLE:
            return r
        last = r
    last["detail"] = f"still throttled after {len(BACKOFF_SEC)} retries: {last.get('detail','')}"
    return last


def fetch_leader(slug: str, candidates: list[dict], target: int, out_dir: Path,
                 min_words: int, force: bool, limiter: RateLimiter) -> list[dict]:
    """Walk a leader's ranked candidates until `target` transcripts are on disk.

    Candidates come pre-ranked by duration. Stopping early is the point: it means
    one caption request per video rather than a probe plus a fetch, which matters
    because the caption endpoint is the scarcest resource in this pipeline.
    """
    results, got = [], 0
    for c in candidates:
        if got >= target:
            break
        r = fetch_with_retry(c, out_dir, min_words, force, limiter)
        results.append(r)
        if r["status"] in ("ok", "cached"):
            got += 1
    if got < target:
        log(f"  {slug}: only {got}/{target} fetched from {len(results)} candidates tried")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--min-words", type=int, default=700,
                    help="Reject transcripts shorter than this; a 3-minute clip has too little signal to score.")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--target-per-leader", type=int, default=0,
                    help="Stop after N successful transcripts per leader, walking that leader's "
                         "ranked candidate list in order. 0 fetches every row in the manifest.")
    ap.add_argument("--min-interval", type=float, default=1.5,
                    help="Minimum seconds between caption requests across ALL workers. Raise this "
                         "if the run starts collecting ip_blocked_or_ratelimited errors.")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()
    dupes = 0
    with open(args.manifest) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            src = json.loads(line)
            missing = [f for f in REQUIRED_FIELDS if f not in src or src[f] in (None, "")]
            if missing:
                raise SystemExit(f"manifest line {lineno}: missing required fields {missing}")
            key = (src["leader_slug"], src["video_id"])
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            sources.append(src)

    log(f"manifest: {len(sources)} unique sources ({dupes} duplicate video_id rows dropped)")

    limiter = RateLimiter(args.min_interval)
    results: list[dict] = []

    if args.target_per_leader:
        from collections import defaultdict as _dd
        by_leader: dict[str, list[dict]] = _dd(list)
        for s_ in sources:
            by_leader[s_["leader_slug"]].append(s_)
        for slug in by_leader:
            by_leader[slug].sort(key=lambda x: x.get("rank", 999))
        log(f"walking {len(by_leader)} leaders for up to {args.target_per_leader} transcripts each "
            f"(min {args.min_interval}s between caption requests, {args.workers} workers)")
        done = 0
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_leader, slug, cands, args.target_per_leader,
                              out_dir, args.min_words, args.force, limiter): slug
                    for slug, cands in by_leader.items()}
            for fut in cf.as_completed(futs):
                rs = fut.result()
                results.extend(rs)
                done += 1
                ok = sum(1 for x in results if x["status"] in ("ok", "cached"))
                log(f"  leaders done {done}/{len(by_leader)} | {ok} transcripts fetched")
    else:
        done = 0
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_with_retry, s_, out_dir, args.min_words, args.force, limiter): s_
                    for s_ in sources}
            for fut in cf.as_completed(futs):
                r = fut.result()
                results.append(r)
                done += 1
                if done % 10 == 0 or done == len(sources):
                    ok = sum(1 for x in results if x["status"] in ("ok", "cached"))
                    log(f"  progress {done}/{len(sources)} attempted | {ok} succeeded | {done - ok} failed")

    ok = [r for r in results if r["status"] == "ok"]
    cached = [r for r in results if r["status"] == "cached"]
    failed = [r for r in results if r["status"] == "failed"]

    Path(args.errors).parent.mkdir(parents=True, exist_ok=True)
    with open(args.errors, "w") as fh:
        for r in failed:
            fh.write(json.dumps(r) + "\n")

    tax: dict[str, int] = {}
    for r in failed:
        tax[r["error_type"]] = tax.get(r["error_type"], 0) + 1

    print(json.dumps({
        "attempted": len(sources),
        "succeeded": len(ok) + len(cached),
        "newly_fetched": len(ok),
        "cached": len(cached),
        "failed": len(failed),
        "error_taxonomy": tax,
        "total_words": sum(r.get("words", 0) for r in ok),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
