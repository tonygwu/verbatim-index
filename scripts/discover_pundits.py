#!/usr/bin/env python3
"""Find long-form recordings for each pundit: own channels first, then strictly matched search results.

Pundits plan, P6. discover_sources.py was built for executives and fails in two
ways this study cannot accept. It matches on the surname alone, with fuzzy
spelling, which put 44 wrong-person recordings into the leaders corpus. And it
rejects "reacts", "debate", "vs" and "responds to", which are how much of
political commentary is published. So this is a separate discoverer:

  - OWN CHANNELS. Each roster own channel is listed through its /videos and
    /streams tabs. Its canonical channel id, not its display name, proves who
    uploaded a video. It does NOT prove who speaks; speaker verification does.
  - SEARCH. Queries come from the name, the handles and the show. A result on
    a channel that is not one of the person's own channels needs the full name
    or a handle, AND a second identity token that is not part of that name or
    handle. There is no surname match and no fuzzy match.
  - TITLES. Clips, compilations, trailers and tributes are rejected. Reaction,
    debate, "vs" and "responds to" titles are allowed.
  - LENGTH. 30 to 180 minutes. A longer recording is excluded, never trimmed.
  - DATES. Flat channel listings carry no upload date (measured 2026-09-14:
    `%(upload_date)s` prints NA on /videos and /streams), so the date window is
    applied after fetch, from the record's `yt_upload_date`, at selection.

Every candidate that is seen ends as accepted or rejected with a reason, and
the counts add up. The output has the shape sources_to_manifest.py reads, and
each source also carries `channel_id`, `discovery_path` and `discovery_stratum`
for selection. `kind` stays inside the manifest's vocabulary: own-channel
uploads are `podcast`, everything else `interview`. The stratum is provisional,
because the judges' venue decides the published one.

  .venv/bin/python scripts/discover_pundits.py --study pundits \
      --roster data-pundits/roster/final.json --out data-pundits/sources/discovered.json \
      [--only slug,slug] [--listing-depth 600]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_SEC = 1800
MAX_SEC = 10800
LISTING_DEPTH = 600
SEARCH_N = 40

REJECT_TITLE = re.compile(
    r"\b(best of|highlights?|supercut|compilation|clips?|documentary|biography|top \d+|"
    r"in \d+ minutes|#?shorts?|trailer|teaser|ai voice|deepfake|parody|tribute|memorial|"
    r"funeral|remembering|rip)\b", re.I)
REJECT_CHANNEL = re.compile(r"\b(clips|shorts|highlights|fan|fans|moments|best of|archive|tribute)\b", re.I)
DEBATE_TITLE = re.compile(r"\b(debates?|debating|vs\.?|versus|responds? to|reacts? to|reaction)\b", re.I)
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _phrase(phrase: str, case_sensitive: bool = False) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", 0 if case_sensitive else re.I)


def mentions(text: str, phrase: str, case_sensitive: bool = False) -> bool:
    return bool(phrase and phrase.strip()) and bool(_phrase(phrase.strip(), case_sensitive).search(text or ""))


def identity(candidate: dict, person: dict) -> tuple[str | None, str]:
    """(path, reason). path is None when the candidate does not identify the person.

    Handles are matched case-sensitively, because several are ordinary words:
    "Destiny" in a title names the streamer, "destiny" does not.
    """
    own = {ch["channel_id"] for ch in person.get("own_channels") or []}
    if candidate.get("channel_id") and candidate["channel_id"] in own:
        return "own_channel", "uploaded by a roster own channel"
    text = f"{candidate.get('title', '')} || {candidate.get('channel', '')}"
    anchors = [(person["name"], False)] + [(h, True) for h in person.get("handles") or []]
    hit = next((a for a, cs in anchors if mentions(text, a, cs)), None)
    if hit is None:
        return None, "neither the full name nor a handle is in the title or channel"
    anchor_words = {w.lower() for a, _ in anchors for w in re.split(r"\s+", a)}
    seconds = [t for t in person.get("identity_tokens") or []
               if not {w.lower() for w in re.split(r"\s+", t)} <= anchor_words
               and not any(mentions(t, a, cs) for a, cs in anchors)]
    token = next((t for t in seconds if mentions(text, t)), None)
    if token is None:
        return None, f"`{hit}` appears without a second identity token"
    return "search_identity", f"`{hit}` with `{token}`"


def title_rejection(candidate: dict, external: bool) -> str | None:
    d = candidate.get("duration")
    if not isinstance(d, int):
        return "duration unknown"
    if d < MIN_SEC:
        return f"too short ({d // 60}m)"
    if d > MAX_SEC:
        return f"too long ({d // 60}m); excluded, not trimmed"
    if REJECT_TITLE.search(candidate.get("title", "")):
        return "title indicates a clip, compilation, trailer or tribute"
    if external and REJECT_CHANNEL.search(candidate.get("channel", "")):
        return f"channel {candidate.get('channel')!r} publishes clips or fan uploads"
    return None


def stratum(candidate: dict, path: str) -> str:
    if path == "own_channel":
        return "own_channel"
    return "debate" if DEBATE_TITLE.search(candidate.get("title", "")) else "interlocutor"


def _yt_dlp(target: str, depth: int) -> list[dict]:
    proc = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--no-warnings", "--socket-timeout", "30", "--playlist-end", str(depth),
         "--print", "%(id)s\t%(duration)s\t%(channel_id)s\t%(channel)s\t%(title)s", target],
        capture_output=True, text=True, timeout=900)
    out = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or not VIDEO_ID.match(parts[0]):
            continue
        try:
            dur = int(float(parts[1]))
        except ValueError:
            dur = None
        out.append({"video_id": parts[0], "duration": dur,
                    "channel_id": "" if parts[2] == "NA" else parts[2],
                    "channel": "" if parts[3] == "NA" else parts[3], "title": "\t".join(parts[4:])})
    return out


def list_channel(channel: dict, depth: int) -> list[dict]:
    base = channel["url"].rstrip("/")
    rows = []
    for tab in ("videos", "streams"):
        for r in _yt_dlp(f"{base}/{tab}", depth):
            rows.append({**r, "channel_id": channel["channel_id"], "channel": r["channel"] or channel["channel_name"]})
    return rows


def search(query: str) -> list[dict]:
    return _yt_dlp(f"ytsearch{SEARCH_N}:{query}", SEARCH_N)


def queries_for(person: dict) -> list[str]:
    name = person["name"]
    qs = [f"{name} interview", f"{name} debate", f"{name} podcast", f"{name} full episode"]
    qs += [f"{h} debate" for h in person.get("handles") or []]
    qs.append(person["show"])
    return list(dict.fromkeys(qs))


def discover(person: dict, depth: int = LISTING_DEPTH, lister=list_channel, searcher=search) -> dict:
    seen: dict[str, dict] = {}
    for ch in person.get("own_channels") or []:
        for r in lister(ch, depth):
            seen.setdefault(r["video_id"], r)
    for q in queries_for(person):
        for r in searcher(q):
            seen.setdefault(r["video_id"], r)

    sources, rejected = [], []
    titles: set[str] = set()
    for vid in sorted(seen):
        c = seen[vid]
        path, why = identity(c, person)
        external = path != "own_channel"
        reason = title_rejection(c, external) or (None if path else why)
        if reason is None:
            key = re.sub(r"[^a-z0-9]+", "", c["title"].lower())[:48]
            if key in titles:
                reason = "same title already accepted (re-upload)"
            titles.add(key)
        if reason:
            rejected.append({**c, "reason": reason})
            continue
        sources.append({
            "source_id": (re.sub(r"[^a-z0-9]+", "-", c["channel"].lower())[:24].strip("-") or "src")
                         + "-" + vid[:6].lower(),
            "video_id": vid, "title": c["title"], "venue": c["channel"], "channel_id": c.get("channel_id", ""),
            "kind": "podcast" if path == "own_channel" else "interview",
            "year": 0, "duration_min": c["duration"] // 60,
            "discovery_path": path, "discovery_stratum": stratum(c, path), "identity_evidence": why,
        })
    for i, s in enumerate(sources, 1):
        s["rank"] = i
    return {"leader_slug": person["slug"], "aliases": [], "repairs": [], "sources": sources,
            "rejected": rejected, "attempted": len(seen),
            "accepted_by_stratum": dict(Counter(s["discovery_stratum"] for s in sources)),
            "rejection_reasons": dict(Counter(r["reason"].split(" (")[0] for r in rejected))}


def main() -> int:
    import study_profile as SP
    from atomicio import write_atomic
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--roster", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default=None)
    ap.add_argument("--listing-depth", type=int, default=LISTING_DEPTH)
    ap.add_argument("--workers", type=int, default=4)
    SP.add_study_arg(ap)
    args = ap.parse_args()
    SP.guard(args.study, args.roster, args.out)
    roster = json.loads(Path(args.roster).read_text())["roster"]
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = sorted(want - {p["slug"] for p in roster})
        if unknown:
            raise SystemExit(f"REFUSING: --only names people not on the roster: {unknown}")
        roster = [p for p in roster if p["slug"] in want]
    results, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(discover, p, args.listing_depth): p for p in roster}
        for fut in cf.as_completed(futs):
            p = futs[fut]
            try:
                r = fut.result()
                results.append(r)
                print(f"  {p['slug']:22} attempted {r['attempted']:4}  accepted {len(r['sources']):4} "
                      f"{r['accepted_by_stratum']}", file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001 -- recorded, and the run exits 1
                failed.append({"leader_slug": p["slug"], "error": f"{type(exc).__name__}: {exc}"})
    results.sort(key=lambda r: r["leader_slug"])
    write_atomic(Path(args.out), json.dumps({"leaders": results, "failed": failed}, indent=1))
    print(json.dumps({"people": len(results), "failed": failed,
                      "attempted": sum(r["attempted"] for r in results),
                      "accepted": sum(len(r["sources"]) for r in results),
                      "by_stratum": dict(sum((Counter(r["accepted_by_stratum"]) for r in results), Counter()))},
                     indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
