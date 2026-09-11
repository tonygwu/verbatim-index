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
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REQUIRED_FIELDS = ("leader_slug", "source_id", "video_id", "title", "venue", "kind", "year")

# Error taxonomy. Every failure maps to exactly one of these.
E_NO_TRANSCRIPT = "no_transcript_available"
E_DISABLED = "transcripts_disabled"
E_UNAVAILABLE = "video_unavailable"
E_BLOCKED = "ip_blocked_or_ratelimited"
E_NOT_ENGLISH = "no_english_track"
E_TOO_SHORT = "below_min_words"
E_METADATA = "metadata_fetch_failed"
E_TIMEOUT = "http_timeout"
E_OTHER = "other"

_print_lock = threading.Lock()

# Pacing follows the yt-dlp wiki, which is the only primary source with numbers:
# a guest session gets roughly 1000 requests an hour, and 5 to 10 seconds between
# requests is the stated remedy for HTTP 429. The first version of this file used
# 1.5 seconds, which is about four times too fast, and the IP was blocked within
# the hour. The rate that triggers a CAPTION block specifically is not documented
# anywhere; do not invent one.
DEFAULT_INTERVAL = 6.0


class Pacer:
    """One shared gap between every outbound request, across all threads.

    Jittered, for two reasons. A fixed gap is a machine fingerprint that anti-bot
    systems can key on. It also resynchronises threads: workers that all back off
    by exactly the same amount wake in the same instant and produce a burst larger
    than the one that caused the block.
    """

    def __init__(self, interval: float, max_interval: float = 15.0):
        self.interval = interval
        self.max_interval = max_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            # Reserve the slot under the lock, then sleep outside it, so waiting
            # threads do not serialise behind one another's sleep.
            self._next = start + self.interval * random.uniform(0.7, 1.3)
            sleep_for = start - now
        if sleep_for > 0:
            time.sleep(sleep_for)

    def slow_down(self, factor: float = 2.0) -> float:
        """Widen permanently. A rate that got pushed back on was too fast.

        One-way WITHIN a pass, and the ceiling is what keeps that honest. The
        ceiling used to be 90s with no way to set it, which let a throttled pass
        hide: cycle 43 on 2026-09-10 pinned the gap at 90s in its first minutes,
        then ground for six hours over 6 of 14 leaders while throttling 158 more
        times. Breaker never fired, because record_ok() clears its consecutive
        counter on every success and at 90s most requests do succeed. So a
        refusing endpoint read as slow rather than stopping, which is the exact
        case Breaker exists to catch, and nobody was ever asked to rotate the IP.
        A ceiling low enough to stay uncomfortable keeps the throttles coming
        until Breaker trips and the loop asks for the cheap fix.
        """
        with self._lock:
            self.interval = min(self.interval * factor, self.max_interval)
            return self.interval


class Breaker:
    """Ends the run once the endpoint is plainly refusing us.

    Without this, each thread backs off privately while the others keep hammering,
    and a hard block reads as "slow" for an hour instead of stopping.
    """

    def __init__(self, limit: int = 4):
        self.limit = limit
        self._lock = threading.Lock()
        self._consecutive = 0
        self.open = False

    def record_throttle(self) -> bool:
        with self._lock:
            self._consecutive += 1
            if self._consecutive >= self.limit:
                self.open = True
            return self.open

    def record_ok(self) -> None:
        with self._lock:
            self._consecutive = 0


# Retry only these. Everything else is a fact about the video that will not
# change, and retrying it spends rate budget on an answer that cannot differ.
THROTTLE_CLASSES = {"IpBlocked", "RequestBlocked", "TooManyRequests"}
PERMANENT_CLASSES = {
    "TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable", "VideoUnplayable",
    "AgeRestricted", "InvalidVideoId", "NotTranslatable", "TranslationLanguageNotAvailable",
}
AMBIGUOUS_CLASSES = {"PoTokenRequired", "YouTubeRequestFailed"}

# Retry is now cheap to abandon, because recovery is an IP rotation rather
# than a wait. Trip fast and hand back rather than grinding through backoff.
BACKOFF_BASE = 3
BACKOFF_CAP = 20
MAX_TRIES = 2


def log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# youtube_transcript_api builds a plain requests.Session and sets no timeout
# anywhere in its source, so a stalled connection blocks the calling thread for
# as long as the kernel keeps the socket open. MEASURED 2026-09-08: one worker
# sat ESTABLISHED to a YouTube address at 0.0% CPU for 21h19m. The loop reported
# itself running the whole time and grade_loop.sh kept printing "fetch loop is
# still running. waiting." every six minutes. Nothing in the pipeline could tell
# a stall from slow work.
HTTP_TIMEOUT_DEFAULT = 60.0


class TimeoutSession(requests.Session):
    """A Session that applies a default timeout to every request it makes.

    The library calls its http_client itself, for the caption LIST and again for
    the caption FETCH, so passing a timeout at one call site would leave the
    other unbounded. Defaulting it on the session covers both, and an explicit
    per-call timeout still wins.
    """

    def __init__(self, timeout: float = HTTP_TIMEOUT_DEFAULT) -> None:
        super().__init__()
        self.timeout = timeout

    def request(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self.timeout)
        return super().request(*args, **kwargs)


def classify(exc: Exception) -> str:
    """Map an exception to the taxonomy by CLASS NAME, not message text.

    Message matching was the first version and it was wrong: "blocked" appears in
    unrelated messages, and a class name is the library's actual contract.
    """
    name = type(exc).__name__
    # requests raises ConnectTimeout and ReadTimeout, both subclasses of
    # Timeout. A stall is NOT E_OTHER: it is the one failure that used to be
    # invisible, so it gets its own label and stays countable.
    if isinstance(exc, requests.exceptions.Timeout):
        return E_TIMEOUT
    if name in THROTTLE_CLASSES:
        return E_BLOCKED
    if name == "TranscriptsDisabled":
        return E_DISABLED
    if name == "NoTranscriptFound":
        return E_NO_TRANSCRIPT
    if name in ("VideoUnavailable", "VideoUnplayable", "InvalidVideoId", "AgeRestricted"):
        return E_UNAVAILABLE
    if name in AMBIGUOUS_CLASSES:
        return E_BLOCKED
    if name in PERMANENT_CLASSES:
        return E_NO_TRANSCRIPT
    return E_OTHER


def fetch_metadata(video_id: str, pacer: "Pacer | None" = None) -> dict:
    """Pull title, channel, duration, upload date and description via yt-dlp.

    Metadata failure is non-fatal: the transcript is still usable, we just
    record that the metadata is missing rather than inventing values.
    """
    # This is a second outbound request per item. Leaving it outside the pacer
    # made the real request rate roughly double the configured one, which the
    # limiter could not see and could not correct for.
    if pacer is not None:
        pacer.wait()
    try:
        proc = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--no-warnings",
                # yt-dlp's own throttling, separate from our pacer. Its wiki
                # suggests these for HTTP 429; --sleep-interval does NOT cover
                # metadata extraction, --sleep-requests does.
                "--sleep-requests", "0.75",
                "--extractor-retries", "3",
                "--retry-sleep", "extractor:exp=1:120",
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


def fetch_one(src: dict, out_dir: Path, min_words: int, force: bool,
              pacer: "Pacer | None" = None,
              timeout: float = HTTP_TIMEOUT_DEFAULT) -> dict:
    slug = src["leader_slug"]
    sid = src["source_id"]
    vid = src["video_id"]
    dest = out_dir / slug / f"{sid}.json"

    if dest.exists() and not force:
        return {"status": "cached", "leader_slug": slug, "source_id": sid, "path": str(dest)}

    # dedupe_transcripts.py --sweep retires a duplicate by renaming it to
    # <source_id>.json.superseded, which `dest.exists()` above does not see. So
    # the fetcher used to download it again on the next cycle, the sweep retired
    # it again on the cycle after, and the pair never settled. That churn spends
    # the YouTube caption allowance, which is the scarcest resource here. The
    # retirement is a decision about this source, so honour it, and let --force
    # override it the way it overrides the cache.
    superseded = dest.with_name(dest.name + ".superseded")
    if superseded.exists() and not force:
        return {"status": "superseded", "leader_slug": slug, "source_id": sid,
                "path": str(superseded),
                "detail": "retired as a duplicate by dedupe_transcripts.py --sweep"}

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_OTHER, "detail": "youtube_transcript_api not importable"}

    try:
        api = YouTubeTranscriptApi(http_client=TimeoutSession(timeout))
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

    meta = fetch_metadata(vid, pacer)
    duration = meta.get("yt_duration_sec") or (segments[-1]["start"] + segments[-1]["duration"] if segments else None)

    record = {
        "leader_slug": slug,
        "source_id": sid,
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "declared_title": src["title"],
        "declared_venue": src["venue"],
        "declared_kind": src["kind"],
        "declared_year": declared_year(src, meta),
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
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)
    return {"status": "ok", "leader_slug": slug, "source_id": sid,
            "words": words, "track": track_kind, "path": str(dest)}


def declared_year(src: dict, meta: dict) -> int:
    """The year the judge will be told. YouTube's upload date first, the
    manifest second, 0 when neither says.

    FOUND 2026-09-10: every manifest row said 2024, because
    sources_to_manifest.py defaulted a missing year to 2024, and this record
    copied it while already carrying `yt_upload_date` from the same fetch.
    479 of 535 dated transcripts disagreed with the year in their own prompt,
    by up to 15 years. 0 is rendered as "unknown" by grade.py; it is never a
    number the judge could mistake for a date.
    """
    upload = str(meta.get("yt_upload_date") or "")
    if len(upload) == 8 and upload.isdigit():
        return int(upload[:4])
    return int(src.get("year") or 0)


def fetch_with_retry(src: dict, out_dir: Path, min_words: int, force: bool,
                     pacer: Pacer, breaker: Breaker,
                     timeout: float = HTTP_TIMEOUT_DEFAULT) -> dict:
    """One source. Retried only for throttling; everything else fails immediately."""
    last = None
    for attempt in range(MAX_TRIES):
        if breaker.open:
            return {"status": "failed", "leader_slug": src["leader_slug"],
                    "source_id": src["source_id"], "error_type": E_BLOCKED,
                    "detail": "circuit open: endpoint refusing consistently, run aborted"}
        pacer.wait()
        r = fetch_one(src, out_dir, min_words, force, pacer, timeout)
        # A stall and a block are different failures and keep different labels,
        # but they call for the same response: back off. Feeding E_TIMEOUT to
        # the breaker as well stops a silently stalling endpoint from resetting
        # it on every attempt and being hammered at full pace.
        if r["status"] != "failed" or r.get("error_type") not in (E_BLOCKED, E_TIMEOUT):
            breaker.record_ok()
            return r
        last = r
        if breaker.record_throttle():
            log(f"    CIRCUIT OPEN after {breaker.limit} consecutive throttles; aborting run")
            r["detail"] = "circuit opened: " + str(r.get("detail", ""))[:200]
            return r
        pace = pacer.slow_down()
        # Full jitter: sleep uniformly in [0, backoff] rather than exactly backoff.
        delay = random.uniform(0, min(BACKOFF_BASE * 2 ** attempt, BACKOFF_CAP))
        log(f"    throttled {src['video_id']}: try {attempt + 1}/{MAX_TRIES}, "
            f"sleeping {delay:.0f}s, pace widened to {pace:.1f}s")
        time.sleep(delay)
    last["detail"] = f"still throttled after {MAX_TRIES} tries: {last.get('detail', '')}"[:400]
    return last


def fetch_leader(slug: str, candidates: list[dict], target: int, out_dir: Path,
                 min_words: int, force: bool, pacer: Pacer, breaker: Breaker,
                 timeout: float = HTTP_TIMEOUT_DEFAULT) -> list[dict]:
    """Walk a leader's ranked candidates until `target` transcripts are on disk.

    Candidates come pre-ranked by duration. Stopping early is the point: it means
    one caption request per video rather than a probe plus a fetch, which matters
    because the caption endpoint is the scarcest resource in this pipeline.
    """
    results, got = [], 0
    for c in candidates:
        if got >= target:
            break
        if breaker.open:
            break
        r = fetch_with_retry(c, out_dir, min_words, force, pacer, breaker, timeout)
        results.append(r)
        if r["status"] in ("ok", "cached"):
            got += 1
        # A superseded candidate is deliberately NOT counted toward the target.
        # It is a second copy of an appearance already held, so it adds no
        # coverage, and counting it would let a leader sit below target for ever
        # while believing it had arrived.
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
    ap.add_argument("--have-dir", default=None,
                    help="Directory counted when deciding whether a leader has already "
                         "reached --target-per-leader. Defaults to --out. The loop passes "
                         "data/transcripts_blind, because the target means GRADEABLE "
                         "transcripts: a leader whose fetches are rejected by QA has not "
                         "reached the target no matter how many raw files are on disk.")
    ap.add_argument("--target-per-leader", type=int, default=0,
                    help="Stop after N successful transcripts per leader, walking that leader's "
                         "ranked candidate list in order. 0 fetches every row in the manifest.")
    ap.add_argument("--http-timeout", type=float, default=HTTP_TIMEOUT_DEFAULT,
                    help="Seconds any single caption request may wait before it is abandoned. "
                         "The library sets none, so without this a stalled socket blocks a "
                         "worker until the kernel gives up.")
    ap.add_argument("--min-interval", type=float, default=2.0,
                    help="Minimum seconds between caption requests across ALL workers, jittered. "
                         "The yt-dlp wiki suggests 5 to 10 seconds as the remedy for HTTP 429.")
    ap.add_argument("--max-interval", type=float, default=15.0,
                    help="Ceiling the shared gap may widen to when the endpoint pushes back. "
                         "Deliberately LOW. Recovery here is an IP rotation, not patience, so a "
                         "throttled pass should keep tripping the circuit breaker and ask for a "
                         "new exit rather than grinding quietly at a comfortable pace.")
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

    pacer = Pacer(args.min_interval, max_interval=args.max_interval)
    breaker = Breaker()
    results: list[dict] = []

    if args.target_per_leader:
        from collections import defaultdict as _dd
        by_leader: dict[str, list[dict]] = _dd(list)
        for s_ in sources:
            by_leader[s_["leader_slug"]].append(s_)
        for slug in by_leader:
            by_leader[slug].sort(key=lambda x: x.get("rank", 999))

        # Fewest-first. A circuit trip mid-run leaves everyone still queued with
        # zero attempts, so a fixed order would starve the same leaders every
        # cycle and make coverage a function of queue position. Ordering by
        # current coverage spends each cycle's budget where it is thinnest, and
        # drops leaders already at target entirely.
        # Count GRADEABLE transcripts, not raw fetches, when one is available.
        # FOUND 2026-09-09: the target was measured against data/transcripts, so a
        # leader whose transcripts fail QA stopped short. Michael Dell had 16 raw
        # files and 9 that survived QA against a target of 14, and the loop
        # reported him "at target" and exited. He is scored on the thinnest
        # evidence on the board as a direct result.
        have_dir = Path(args.have_dir) if args.have_dir else out_dir
        def _have(slug: str) -> int:
            d = have_dir / slug
            return len([f for f in d.glob("*.json") if not f.name.endswith(".tmp")]) if d.exists() else 0

        ordered = sorted(by_leader.items(), key=lambda kv: (_have(kv[0]), kv[0]))
        ordered = [(slug, cands) for slug, cands in ordered if _have(slug) < args.target_per_leader]
        skipped = len(by_leader) - len(ordered)
        if skipped:
            log(f"  {skipped} leaders already at target, skipping them this pass")
        by_leader = dict(ordered)
        log(f"walking {len(by_leader)} leaders for up to {args.target_per_leader} transcripts each "
            f"(min {args.min_interval}s between caption requests, {args.workers} workers)")
        done = 0
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_leader, slug, cands, args.target_per_leader,
                              out_dir, args.min_words, args.force, pacer, breaker,
                              args.http_timeout): slug
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
            futs = {ex.submit(fetch_with_retry, s_, out_dir, args.min_words, args.force, pacer,
                              breaker, args.http_timeout): s_
                    for s_ in sources}
            for fut in cf.as_completed(futs):
                r = fut.result()
                results.append(r)
                done += 1
                if done % 10 == 0 or done == len(sources):
                    ok = sum(1 for x in results if x["status"] in ("ok", "cached"))
                    sup = sum(1 for x in results if x["status"] == "superseded")
                    log(f"  progress {done}/{len(sources)} attempted | {ok} succeeded | "
                        f"{sup} skipped as retired duplicates | {done - ok - sup} failed")

    ok = [r for r in results if r["status"] == "ok"]
    cached = [r for r in results if r["status"] == "cached"]
    superseded = [r for r in results if r["status"] == "superseded"]
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
        # Retired as a duplicate by the sweep. Neither a success nor a failure,
        # so it gets its own line rather than silently unbalancing the tally.
        "superseded": len(superseded),
        "failed": len(failed),
        "error_taxonomy": tax,
        "total_words": sum(r.get("words", 0) for r in ok),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
