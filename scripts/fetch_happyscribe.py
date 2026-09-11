#!/usr/bin/env python3
"""Fetch transcripts from Happy Scribe, as a second source alongside YouTube.

Why a second source at all: YouTube's caption endpoint rate-limits per IP and
has blocked this pipeline repeatedly. Happy Scribe is a different host with a
different limit, so the two can run at the same time and neither one stalls the
other.

Two things verified before this was written, both by measurement:
  - robots.txt permits everything except /surprise-me and /search, and names no
    Anthropic-specific rule.
  - HTTP/2 draws a Cloudflare 403 and HTTP/1.1 returns 200. The requests
    Session below is pinned to HTTP/1.1 for that reason.

Output records match the YouTube fetcher's shape exactly, with
`fetch_method: happyscribe`, so every downstream stage treats them identically.
Deduplication against the YouTube corpus is a SEPARATE step, in
dedupe_transcripts.py. This script never decides what to keep; it only fetches.

Usage:
  fetch_happyscribe.py --discover --roster data/roster/final.json \
      --candidates data/sources/happyscribe_candidates.json
  fetch_happyscribe.py --report-unsearched --roster data/roster/final.json \
      --candidates data/sources/happyscribe_candidates.json
  fetch_happyscribe.py --fetch --candidates data/sources/happyscribe_candidates.json \
      --out data/transcripts_hs --target-per-leader 5
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html as htmlmod
import json
import os
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://podcasts.happyscribe.com"
SITEMAP_INDEX = f"{BASE}/sitemap.xml"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0 Safari/537.36")

# robots.txt disallows exactly these. Checked 2026-09-06; re-check if this
# script starts 403ing rather than assuming the block is rate-based.
ROBOTS_DISALLOW = ("/surprise-me", "/search")

E_HTTP = "http_error"
E_NO_TRANSCRIPT = "no_transcript_in_page"
E_TOO_SHORT = "below_min_words"
E_BLOCKED = "blocked_or_ratelimited"
E_OTHER = "other"

MIN_WORDS = 700
_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, file=sys.stderr, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_session() -> requests.Session:
    """A session pinned to HTTP/1.1, which is the only version that works here."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    # requests uses HTTP/1.1 by default. Stated explicitly because it is
    # load-bearing: HTTP/2 returns 403 from this host.
    return s


class Pacer:
    """Shared, jittered gap between requests. Same discipline as the YouTube path."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval * random.uniform(0.7, 1.3)
            gap = start - now
        if gap > 0:
            time.sleep(gap)


def allowed(path: str) -> bool:
    return not any(path.startswith(d) for d in ROBOTS_DISALLOW)


# Shared with the YouTube discovery path so both sources apply one definition of
# "this is commentary, not an appearance". The transcript-stage name-density gate
# in qa_transcripts.py is the backstop for whatever slips through here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_sources import THIRD_PERSON_TITLE  # noqa: E402

# Episode slugs carry commentary shapes the video-title filter never had to
# handle: "why-X-is-selling-stock", "scale-like-X", "X explained". These are
# people talking ABOUT the leader. Caught here to avoid wasting fetches; the
# name-density gate in qa_transcripts.py remains the real defence, because it
# measures the transcript rather than guessing from a slug.
COMMENTARY_SLUG = re.compile(
    r"(^|-)(why|how|what|when|lessons?|secrets?|rules?|habits?|advice|playbook|"
    r"strategy|blueprint|method|mindset|genius|empire|downfall|scandal)(-|$)"
    r"|(^|-)(like|about|behind|inside|vs|versus|reacts?|reaction|explained|"
    r"analysis|breakdown|recap|review)(-|$)", re.I)


# ---------------------------------------------------------------- discovery

def get(session: requests.Session, url: str, pacer: Pacer, timeout: int = 60) -> requests.Response:
    pacer.wait()
    return session.get(url, timeout=timeout, allow_redirects=True)


def unsearched_leaders(roster_path, pool_path) -> tuple[list[str], list[str]]:
    """Which roster slugs the candidate pool has never been searched for.

    Returns (unsearched, stale). The pool is DERIVED from the roster, so it has
    to track it. happyscribe_loop.sh used to run discovery only when the pool
    file was missing, which meant the roster could move underneath it forever.
    It did: the roster grew from 40 to 50 on 2026-09-10 and eleven leaders were
    never searched, while C.C. Wei stayed in the pool after being removed from
    the study. The loop reported COMPLETE the whole time, truthfully, because
    every candidate it knew of had been fetched. It simply knew of none for them.

    A leader PRESENT with an empty list counts as SEARCHED. Larry Ellison,
    Michael Dell and Sergey Brin were searched and genuinely have no podcast
    appearances, so treating empty as unsearched would re-walk 38 sitemaps every
    cycle forever and hide the real gap behind constant activity.

    An absent or empty pool file means nobody has been searched, rather than an
    error: that is the first-run case the loop already handles.
    """
    roster = [r["slug"] for r in json.loads(Path(roster_path).read_text())["roster"]]
    pool_path = Path(pool_path)
    pool: dict = {}
    if pool_path.is_file() and pool_path.stat().st_size:
        pool = json.loads(pool_path.read_text())
    unsearched = [s for s in roster if s not in pool]
    stale = [k for k in pool if k not in roster]
    return unsearched, sorted(stale)


def discover(roster: list[dict], session: requests.Session, pacer: Pacer,
             max_sitemaps: int = 40) -> dict:
    """Walk the sitemap index and keep episodes whose slug names one of our leaders.

    Matching on the EPISODE SLUG rather than on a show allowlist. An episode
    slug reliably carries the guest's name, e.g. "405-jeff-bezos-amazon-and-blue-
    origin", so this finds appearances on shows we never thought to list, and it
    does not depend on guessing show slugs correctly.
    """
    r = get(session, SITEMAP_INDEX, pacer)
    r.raise_for_status()
    children = re.findall(r"<loc>([^<]+)</loc>", r.text)
    log(f"sitemap index: {len(children)} child sitemaps")

    # FULL NAME ONLY. Surname matching was tried and produced garbage: "prince"
    # matched 23 episodes about Prince Harry, Saudi princes and Jordanian
    # princes, none of them Cloudflare's chief executive. A surname that is also
    # an ordinary English word cannot carry this on its own.
    keys: list[tuple[str, str]] = []
    for p in roster:
        parts = [w for w in re.split(r"\s+", p["name"]) if len(w) > 1]
        keys.append((p["slug"], "-".join(w.lower() for w in parts)))

    seen: set[str] = set()
    found: dict[str, list[dict]] = {p["slug"]: [] for p in roster}
    for i, child in enumerate(children[:max_sitemaps], 1):
        try:
            rc = get(session, child, pacer)
            if rc.status_code != 200:
                log(f"  sitemap {i}/{len(children)}: HTTP {rc.status_code}, skipping")
                continue
        except Exception as exc:  # noqa: BLE001
            log(f"  sitemap {i}/{len(children)}: {type(exc).__name__}, skipping")
            continue
        urls = re.findall(r"<loc>([^<]+)</loc>", rc.text)
        hits = 0
        for u in urls:
            clean = u.split("?")[0]
            path = clean[len(BASE):] if clean.startswith(BASE) else clean
            if not allowed(path) or clean in seen:
                continue
            segs = [s for s in path.split("/") if s]
            if len(segs) != 2:
                continue
            show, ep = segs
            low = f"{show}/{ep}".lower()
            # A slug can name the person and still be a show ABOUT them rather
            # than an appearance BY them: "why-jeff-bezos-is-selling-amazon-stock"
            # names him and is commentary. Reuse the same third-person filter the
            # YouTube discovery uses, so both sources reject the same shapes.
            if THIRD_PERSON_TITLE.search(ep.replace("-", " ")) or COMMENTARY_SLUG.search(ep):
                continue
            for slug, full in keys:
                if full not in low:
                    continue
                seen.add(clean)
                found[slug].append({"url": clean, "show": show, "episode": ep})
                hits += 1
                break
        if i % 10 == 0 or hits:
            total = sum(len(v) for v in found.values())
            log(f"  sitemap {i}/{len(children)}: +{hits} (running total {total})")

    return found


# ------------------------------------------------------------------- fetch

TRANSCRIPT_BLOCK = re.compile(
    r'<div[^>]*class="[^"]*episode-transcription-body[^"]*"[^>]*>(.*?)</div>\s*(?:</div>|<footer)',
    re.S | re.I)
TS = re.compile(r"\[(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?\]")


def extract_transcript(page: str) -> tuple[str, int]:
    """Pull the transcript and normalise timestamps to [hh:mm:ss].

    The page renders the transcript TWICE. A JSON payload early in the document
    carries it with timestamps intact, and a later HTML block repeats it with
    the timestamps stripped. Scraping the visible HTML looks like the obvious
    move and silently loses all 576 position markers, which are what lets a
    judge cite where in an appearance a passage sits. So the JSON field is the
    primary path and the HTML block is only a fallback.
    """
    marker = '"transcript":'
    idx = page.find(marker)
    if idx != -1:
        # Decode the JSON string properly rather than regexing to the next quote:
        # the transcript contains escaped quotes and would be truncated.
        q = page.find('"', idx + len(marker))
        if q != -1:
            try:
                raw, _ = json.JSONDecoder().raw_decode(page[q:])
                if isinstance(raw, str) and len(raw.split()) > 200:
                    return _normalise(raw)
            except ValueError:
                pass

    m = TRANSCRIPT_BLOCK.search(page)
    chunk = m.group(1) if m else ""
    if not chunk:
        m2 = re.search(r'<section[^>]*class="[^"]*episode-transcript-section[^"]*"[^>]*>(.*?)</section>',
                       page, re.S | re.I)
        chunk = m2.group(1) if m2 else ""
    if not chunk:
        return "", 0
    chunk = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", chunk)
    chunk = re.sub(r"(?s)<[^>]+>", " ", chunk)
    return _normalise(htmlmod.unescape(chunk))


def _normalise(text: str) -> tuple[str, int]:
    """Collapse whitespace and rewrite [hh:mm:ss.ff] as [hh:mm:ss].

    The YouTube fetcher emits [hh:mm:ss], so both sources must agree or a judge
    sees two different citation formats and the rubric's timestamp instruction
    stops meaning one thing.
    """
    text = re.sub(r"[ \t]+", " ", text)
    n_marks = len(TS.findall(text))
    text = TS.sub(lambda m: f"\n[{int(m.group(1)):02d}:{m.group(2)}:{m.group(3)}] ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text, n_marks


def page_meta(page: str) -> dict:
    def grab(pat: str) -> str | None:
        m = re.search(pat, page, re.I | re.S)
        return htmlmod.unescape(m.group(1)).strip() if m else None
    return {
        "hs_title": grab(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')
                    or grab(r"<title>([^<]+)</title>"),
        "hs_description": (grab(r'<meta[^>]+name="description"[^>]+content="([^"]+)"') or "")[:1000],
    }


def fetch_one(cand: dict, slug: str, out_dir: Path, session: requests.Session,
              pacer: Pacer, force: bool) -> dict:
    sid = "hs-" + re.sub(r"[^a-z0-9]+", "-", cand["episode"].lower())[:44].strip("-")
    dest = out_dir / slug / f"{sid}.json"
    if dest.exists() and not force:
        return {"status": "cached", "leader_slug": slug, "source_id": sid}
    try:
        r = get(session, cand["url"], pacer)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_OTHER, "detail": f"{type(exc).__name__}: {exc}"[:300]}
    if r.status_code in (403, 429, 503):
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_BLOCKED, "detail": f"HTTP {r.status_code}"}
    if r.status_code != 200:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_HTTP, "detail": f"HTTP {r.status_code}"}

    text, n_marks = extract_transcript(r.text)
    words = len(text.split())
    if not text:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_NO_TRANSCRIPT, "detail": "no transcript container in page"}
    if words < MIN_WORDS:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_TOO_SHORT, "detail": f"{words} words < {MIN_WORDS}"}

    meta = page_meta(r.text)
    # Duration is inferred from the last timestamp, since the page states none.
    last = TS.findall(text)
    dur = None
    if last:
        h, m_, s = last[-1]
        dur = int(h) * 3600 + int(m_) * 60 + int(s)

    rec = {
        "leader_slug": slug,
        "source_id": sid,
        "video_id": None,
        "url": cand["url"],
        "declared_title": meta.get("hs_title") or cand["episode"],
        "declared_venue": cand["show"],
        "declared_kind": "podcast",
        "declared_year": 0,
        "caption_track": "happyscribe",
        "word_count": words,
        "char_count": len(text),
        "duration_sec": dur,
        "n_timestamp_marks": n_marks,
        "fetched_at_utc": utcnow(),
        "fetch_method": "happyscribe",
        "hs_show": cand["show"],
        "hs_episode": cand["episode"],
        **meta,
        "text": text,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)
    return {"status": "ok", "leader_slug": slug, "source_id": sid, "words": words,
            "path": str(dest)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--roster", default="data/roster/final.json")
    ap.add_argument("--candidates", default="data/sources/happyscribe_candidates.json")
    ap.add_argument("--out", default="data/transcripts_hs")
    ap.add_argument("--errors", default="data/logs/happyscribe_errors.jsonl")
    ap.add_argument("--target-per-leader", type=int, default=5)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-sitemaps", type=int, default=40)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report-unsearched", action="store_true",
                    help="Print the roster slugs absent from the candidate pool and exit. "
                         "The pool is derived from the roster, so the loop uses this to notice "
                         "a roster change instead of assuming one never happens.")
    args = ap.parse_args()

    session = make_session()
    pacer = Pacer(args.interval)

    if args.report_unsearched:
        # Space-separated on stdout so the loop can test it for emptiness, with
        # the detail on stderr so a human reading the log sees who and why.
        unsearched, stale = unsearched_leaders(args.roster, args.candidates)
        if stale:
            print(f"pool holds {len(stale)} leader(s) no longer on the roster: "
                  f"{', '.join(stale)}", file=sys.stderr)
        if unsearched:
            print(f"{len(unsearched)} roster leader(s) never searched: "
                  f"{', '.join(unsearched)}", file=sys.stderr)
        print(" ".join(unsearched))
        return 0

    if args.discover:
        roster = json.loads(Path(args.roster).read_text())["roster"]
        found = discover(roster, session, pacer, args.max_sitemaps)
        Path(args.candidates).parent.mkdir(parents=True, exist_ok=True)
        Path(args.candidates).write_text(json.dumps(found, indent=1))
        n = sum(len(v) for v in found.values())
        with_any = sum(1 for v in found.values() if v)
        print(json.dumps({
            "candidates_found": n,
            "leaders_with_candidates": f"{with_any}/{len(roster)}",
            "per_leader": {k: len(v) for k, v in sorted(found.items()) if v},
            "leaders_with_none": sorted(k for k, v in found.items() if not v),
        }, indent=2))
        return 0

    if not args.fetch:
        ap.error("pass --discover, --fetch or --report-unsearched")

    cands = json.loads(Path(args.candidates).read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for slug, items in sorted(cands.items()):
        have = len(list((out_dir / slug).glob("*.json"))) if (out_dir / slug).exists() else 0
        for c in items[: max(0, args.target_per_leader - have) + 3]:
            jobs.append((slug, c))
    log(f"{len(jobs)} happyscribe pages queued across {len(cands)} leaders "
        f"at {args.interval}s pace, {args.workers} workers")

    results = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c, slug, out_dir, session, pacer, args.force): (slug, c)
                for slug, c in jobs}
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 10 == 0:
                ok = sum(1 for x in results if x["status"] in ("ok", "cached"))
                log(f"  {done}/{len(jobs)} attempted | {ok} succeeded")

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
        "attempted": len(jobs),
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
