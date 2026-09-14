#!/usr/bin/env python3
"""Pundits discovery: own channels by id, strict identity for search results, no surname or fuzzy match.

Pundits plan, P6. No network: the channel lister and the searcher are replaced
with fixtures.

  IDENTITY    an own-channel id passes whatever the title; on another channel
              the full name or a handle needs a second identity token; the name
              alone, the handle alone, the surname alone and a misspelt surname
              all fail; a token that only repeats the handle does not count;
              a handle is matched with its capital, so "destiny" is not Destiny
  TITLES      debate, vs, reacts to and responds to are allowed; clips,
              compilations, shorts and tributes are rejected
  LENGTH      29 and 181 minutes are rejected, 30 and 180 accepted
  STRATA      own channel, debate and interlocutor are assigned as specified
  ACCOUNTING  attempted = accepted + rejected, every rejection has a reason,
              and a video seen twice is counted once
  MANIFEST    every accepted source passes sources_to_manifest's checks: an
              11-character id and a kind inside its vocabulary

  .venv/bin/python scripts/test_discover_pundits.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
OWN = "UC554eY5jNUfDq3yDOJYirOQ"


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


PERSON = {"slug": "steven-bonnell", "name": "Steven Bonnell", "handles": ["Destiny"],
          "show": "Destiny", "outlet": "YouTube",
          "identity_tokens": ["Destiny debates", "OmniLiberal", "Steven Bonnell", "Lex Fridman"],
          "own_channels": [{"url": "https://www.youtube.com/@destiny", "channel_id": OWN, "channel_name": "Destiny"}]}


def cand(vid: str, title: str, channel: str = "Other Show", channel_id: str = "UCother0000000000000000", minutes: int = 60):
    return {"video_id": vid, "title": title, "channel": channel, "channel_id": channel_id, "duration": minutes * 60}


def main() -> int:
    print("pundits discovery")
    import discover_pundits as D

    print("\n[IDENTITY]")
    ident = lambda c: D.identity(c, PERSON)[0]  # noqa: E731
    check("an own-channel id passes with an unrelated title", ident(cand("a" * 11, "Chatting about taxes", "Destiny", OWN)) == "own_channel")
    check("full name with a second token passes", ident(cand("b" * 11, "Steven Bonnell | Lex Fridman Podcast")) == "search_identity")
    check("full name alone fails", ident(cand("c" * 11, "Steven Bonnell on Israel")) is None)
    check("handle with a second token passes", ident(cand("d" * 11, "Destiny talks OmniLiberal ideas")) == "search_identity")
    check("handle alone fails", ident(cand("e" * 11, "Destiny vs Ben Shapiro")) is None)
    check("a token that only repeats the handle is not a second token", ident(cand("f" * 11, "Destiny debates Hasan")) is None)
    check("the surname alone fails", ident(cand("g" * 11, "Bonnell interview | Lex Fridman")) is None)
    check("a misspelt surname fails (no fuzzy match)", ident(cand("h" * 11, "Steven Bonell | Lex Fridman")) is None)
    check("a lowercase ordinary word does not match a handle", ident(cand("i" * 11, "our destiny with OmniLiberal")) is None)
    check("the channel name counts as text for the second token",
          ident(cand("j" * 11, "Steven Bonnell on free speech", channel="Lex Fridman")) == "search_identity")

    print("\n[TITLES]")
    ok = lambda t: D.title_rejection(cand("k" * 11, t), external=True) is None  # noqa: E731
    for t in ("Destiny vs Ben Shapiro", "Destiny debates Hasan", "Destiny reacts to the debate", "Destiny responds to critics"):
        check(f"allowed: {t!r}", ok(t))
    for t in ("Best of Destiny", "Destiny clips compilation", "Destiny #shorts", "Tribute to Destiny"):
        check(f"rejected: {t!r}", not ok(t))
    check("a clip channel is rejected for an external upload",
          D.title_rejection(cand("l" * 11, "Destiny full debate", channel="Destiny Clips"), external=True) is not None)

    print("\n[LENGTH]")
    for minutes, want in ((29, False), (30, True), (180, True), (181, False)):
        got = D.title_rejection(cand("m" * 11, "Steven Bonnell | Lex Fridman", minutes=minutes), external=True) is None
        check(f"{minutes} minutes {'accepted' if want else 'rejected'}", got == want)

    print("\n[STRATA]")
    check("own channel -> own_channel", D.stratum(cand("n" * 11, "Destiny vs X"), "own_channel") == "own_channel")
    check("external debate title -> debate", D.stratum(cand("o" * 11, "Steven Bonnell vs X"), "search_identity") == "debate")
    check("external other -> interlocutor", D.stratum(cand("p" * 11, "Steven Bonnell | Lex Fridman"), "search_identity") == "interlocutor")

    print("\n[ACCOUNTING]")
    own_rows = [cand("A0000000001", "Stream about taxes", "Destiny", OWN, 90),
                cand("A0000000002", "Short stream", "Destiny", OWN, 10),
                cand("A0000000003", "Destiny vs Ben Shapiro", "Destiny", OWN, 120)]
    search_rows = [cand("A0000000003", "Destiny vs Ben Shapiro", "Destiny", OWN, 120),
                   cand("B0000000001", "Steven Bonnell | Lex Fridman Podcast #1", "Lex Fridman", minutes=150),
                   cand("B0000000002", "Bonnell on Israel", minutes=60),
                   cand("B0000000003", "Steven Bonnell | Lex Fridman Podcast #1", "Lex Clips", minutes=150)]
    r = D.discover(PERSON, lister=lambda ch, depth: own_rows, searcher=lambda q: search_rows)
    check("a video seen in the listing and in search is attempted once", r["attempted"] == 6, str(r["attempted"]))
    check("attempted = accepted + rejected", r["attempted"] == len(r["sources"]) + len(r["rejected"]),
          f"{r['attempted']} vs {len(r['sources'])}+{len(r['rejected'])}")
    check("every rejection has a reason", all(x.get("reason") for x in r["rejected"]))
    got = sorted((s["video_id"], s["discovery_stratum"]) for s in r["sources"])
    check("accepted exactly the two own long uploads and the matched interview",
          got == [("A0000000001", "own_channel"), ("A0000000003", "own_channel"), ("B0000000001", "interlocutor")], str(got))

    print("\n[MANIFEST]")
    import sources_to_manifest as M
    check("every accepted source has an 11-character id and a manifest kind",
          all(M.VIDEO_ID.match(s["video_id"]) and s["kind"] in M.KINDS for s in r["sources"]))
    check("ranks run 1..n", [s["rank"] for s in r["sources"]] == list(range(1, len(r["sources"]) + 1)))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
