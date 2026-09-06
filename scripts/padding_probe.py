#!/usr/bin/env python3
"""Build padded variants of one transcript that add WORDS but no INFORMATION.

Purpose
-------
Across 27 real gradings the correlation between transcript word count and
composite score is +0.584. Two stories fit that number equally well:

  LEGITIMATE  a longer conversation gives more opportunity to demonstrate
              reasoning, so more sub-criteria become observable.
  BIAS        the judges reward bulk.

Only a within-transcript manipulation separates them. This script takes one
real transcript and inflates its word count by a fixed target while adding
zero new substance, so a judge that measures substance must not move and a
judge that rewards length must rise.

Three padding styles, each testing a different thing
----------------------------------------------------
  filler    Conversational disfluency inserted INSIDE existing sentences
            ("you know", "I mean", "sort of"). Pure verbosity. Also the most
            damaging to readability, so it is the least clean length test.
  restate   A verbose restatement of a sentence inserted immediately after
            that same sentence. The restatement is a VERBATIM copy of the
            sentence wrapped in a fixed frame, so it can introduce no claim
            that was not already there. Tests elaboration without novelty.
  offtopic  Bland, on-format, contentless pleasantries and logistics inserted
            between sentences. Grammatical and readable, so this is the
            cleanest test of length alone.

Each style is generated at +25% and +60% of the declared word count, giving
six padded variants plus the untouched baseline.

The insertion rules, exactly
----------------------------
Tokenisation
  The text is split with re.split(r'(\\s+)', text) into an alternating list of
  word tokens and whitespace separators. Every token keeps the separator that
  follows it. A token matching ^\\[\\d\\d:\\d\\d:\\d\\d\\]$ is a TIMESTAMP marker and is
  never an insertion anchor and never counts as a sentence word.
  A token ENDS A SENTENCE when it ends in '.', '?' or '!' after trailing
  quotes and brackets are stripped, and its alphanumeric stem is longer than
  one character (so an initial such as "U." does not end a sentence).

Anchors
  filler    anchors are word tokens strictly INSIDE a sentence, that is not
            the sentence's final token and not the token immediately before
            the sentence's final token. Only sentences of >= 6 words are
            eligible, so a filler is never the bulk of the sentence.
  restate   anchors are sentence-final tokens of sentences with >= 10 words
            that do not end in '?'. A question is skipped because restating a
            question as a statement would change its force.
  offtopic  anchors are sentence-final tokens of any sentence.
  No style ever anchors on the last token of the transcript.

How many insertions
  SEED = 20260905. The anchors are shuffled once with random.Random(SEED) and
  swept in that fixed order for up to 8 passes. Each visit places one
  fragment, unless that fragment would push the total past the target. A
  second, fitting phase then closes the residual gap by searching every
  remaining (anchor, phrase) pair for the fragment that lands closest to the
  target. The variant is a pure function of (style, target, SEED).

What gets inserted
  filler    12 discourse markers, drawn from an independent stream
            random.Random(SEED + 1). A phrase is never reused at the same
            anchor.
  offtopic  16 complete contentless sentences, same rule.
  restate   6 frames, same rule. The frame's {s} slot is filled with the
            anchor sentence itself: first character lowercased, terminal
            punctuation replaced by '.'. Nothing else.

Timestamps
  Markers are kept, all 54 of them, and each marker time is multiplied by the
  global word-inflation factor and rounded to whole seconds. duration_sec is
  scaled by the same factor. This holds the speaking rate at the original
  168.6 words per minute and preserves the transcript's natural variation in
  words per block. The cost is that markers now sit 76s (at +25%) or 98s (at
  +60%) apart instead of 61s. The alternative, re-deriving markers at a fixed
  61s, would make every block hold an identical word count, which looks
  synthetic. Monotonicity of the rewritten marker times is asserted.

Integrity gate (run on every variant, fails loud)
  1. Deleting every inserted fragment reproduces the source text BYTE FOR
     BYTE. This is what proves the padding is additive only.
  2. Placeholder accounting. Every original [SUBJECT] and [COMPANY] survives
     untouched by gate 1. The padding may introduce no other bracketed token.
     filler and offtopic must leave the counts identical; restate is allowed
     to raise them, because copying a sentence copies its placeholders, which
     is repetition rather than a change to the blinding.
  3. Every inserted fragment is either an exact member of the style's lexicon
     (and every lexicon entry is asserted digit-free at import), or, for
     restate, is reproduced character for character by applying one of the six
     fixed frames to a sentence already in the transcript. No new number,
     name, or claim can therefore enter.
  4. Marker count unchanged and marker times strictly increasing.
  5. Realised inflation within 0.4% of the target.

Variant naming
  The judge prompt contains the line
      transcript_id must be exactly: <leader_slug>/<source_id>
  so a source_id like "fixture-bigtech-2025-pad-filler-25" would TELL THE
  JUDGE it is reading a padded transcript, which destroys the probe. The
  variants therefore use opaque codes and a fixed, deliberately non-monotone
  mapping (see VARIANTS below) so neither the style nor the magnitude can be
  inferred from the id. leader_slug is left as-is, because changing it would
  move a second variable.

Usage
  python3 scripts/padding_probe.py \
      --fixture data/fixtures_clean/thomas-kurian/fixture-bigtech-2025.json \
      --out data/fixtures_padded
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

SEED = 20260905
MARKER_RE = re.compile(r"^\[\d\d:\d\d:\d\d\]$")
TARGET_TOL = 0.004

# Opaque variant codes. The order is fixed and deliberately not monotone in
# either style or magnitude, so a judge reading the id learns nothing.
VARIANTS = {
    "x1": ("restate", 0.60),
    "x2": ("filler", 0.25),
    "x3": ("offtopic", 0.60),
    "x4": ("restate", 0.25),
    "x5": ("offtopic", 0.25),
    "x6": ("filler", 0.60),
}

FILLERS = [
    "you know",
    "I mean",
    "sort of",
    "kind of",
    "at the end of the day",
    "if that makes sense",
    "to be honest",
    "in a sense",
    "so to speak",
    "you know what I mean",
    "more or less",
    "if you will",
]

OFFTOPIC = [
    "Thanks again for having me on the show.",
    "It is really great to be here with you today.",
    "I appreciate you taking the time to have this conversation.",
    "As I mentioned earlier, this is a topic I am glad we are getting into.",
    "Let me just say that it is a pleasure to be talking about this.",
    "I would be happy to come back and talk about any of this again.",
    "That is a good question and I am glad you asked it.",
    "Before I go on, let me say how much I enjoy these conversations.",
    "It is nice to have the chance to sit down and go through this.",
    "Anyway, that is the sort of thing we end up talking about a lot.",
    "I hope that is useful for the people listening to this.",
    "We can always come back to this later in the conversation if you want.",
    "Sorry, let me pick up the thread where we left it.",
    "That is the kind of thing I always enjoy discussing.",
    "Right, so where were we. Let me carry on from there.",
    "Thanks, and again it is good of you to have me on.",
]

RESTATE_FRAMES = [
    "So what I am saying there is, essentially, {s}",
    "To put that another way, and I want to be clear about it, {s}",
    "Let me say that again in slightly different words. Essentially, {s}",
    "Which is to say, and I think this is worth repeating, {s}",
    "In other words, and I do want to underline this, {s}",
    "Said differently, so that it is not lost in the middle of all this, {s}",
]

for _phrase in FILLERS + OFFTOPIC + RESTATE_FRAMES:
    assert not re.search(r"\d", _phrase), f"lexicon entry carries a digit: {_phrase}"


# --------------------------------------------------------------------------
# tokenisation


def tokenise(text: str) -> list[dict]:
    """Split into word tokens each carrying the whitespace that follows it.

    ''.join(t['w'] + t['sep'] for t in tokens) == text, exactly.
    """
    parts = re.split(r"(\s+)", text)
    toks: list[dict] = []
    i = 0
    while i < len(parts):
        w = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if w == "":
            # leading or trailing empty produced by the split
            if sep:
                if toks:
                    toks[-1]["sep"] += sep
                else:
                    toks.append({"w": "", "sep": sep, "marker": False})
            i += 2
            continue
        toks.append({"w": w, "sep": sep, "marker": bool(MARKER_RE.match(w))})
        i += 2
    return toks


def ends_sentence(word: str) -> bool:
    stem = word.rstrip("\"')]}»”’")
    if not stem or stem[-1] not in ".?!":
        return False
    core = re.sub(r"[^0-9A-Za-z]", "", stem)
    return len(core) > 1


def sentence_spans(toks: list[dict]) -> list[tuple[int, int]]:
    """[(start, end)] inclusive token index ranges. Markers are excluded."""
    spans = []
    start = None
    for i, t in enumerate(toks):
        if t["marker"] or t["w"] == "":
            continue
        if start is None:
            start = i
        if ends_sentence(t["w"]):
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(toks) - 1))
    return spans


def span_words(toks: list[dict], span: tuple[int, int]) -> int:
    return sum(1 for i in range(span[0], span[1] + 1) if not toks[i]["marker"] and toks[i]["w"])


def span_text(toks: list[dict], span: tuple[int, int]) -> str:
    out = []
    for i in range(span[0], span[1] + 1):
        if toks[i]["marker"] or not toks[i]["w"]:
            continue
        out.append(toks[i]["w"])
    return " ".join(out)


# --------------------------------------------------------------------------
# anchors per style


def anchors_for(style: str, toks: list[dict], spans: list[tuple[int, int]]) -> list[dict]:
    last_real = max(i for i, t in enumerate(toks) if t["w"])
    out: list[dict] = []
    if style == "filler":
        for sp in spans:
            if span_words(toks, sp) < 6:
                continue
            inner = [i for i in range(sp[0], sp[1] - 1)
                     if not toks[i]["marker"] and toks[i]["w"] and i != last_real]
            for i in inner:
                out.append({"tok": i})
    elif style == "restate":
        for sp in spans:
            if span_words(toks, sp) < 10:
                continue
            if toks[sp[1]]["w"].rstrip("\"')]}»”’").endswith("?"):
                continue
            if sp[1] == last_real:
                continue
            out.append({"tok": sp[1], "span": sp})
    elif style == "offtopic":
        for sp in spans:
            if sp[1] == last_real:
                continue
            out.append({"tok": sp[1]})
    else:
        raise ValueError(f"unknown style {style}")
    return sorted(out, key=lambda a: a["tok"])


def restatement(toks: list[dict], span: tuple[int, int], frame: str) -> str:
    body = span_text(toks, span)
    body = body.rstrip()
    body = re.sub(r"[.?!]+[\"')\]}»”’]*$", "", body).rstrip()
    first = body.split(" ", 1)[0] if body else ""
    # Lowercase the opening word so the frame reads as one sentence, but never
    # turn the pronoun "I" into "i", and never touch an acronym, a placeholder
    # such as [COMPANY], or a proper noun that is already all caps.
    if (body and body[0].isupper() and first not in ("I", "I'm", "I've", "I'll", "I'd")
            and not first.isupper()):
        body = body[0].lower() + body[1:]
    return frame.format(s=body + ".")


# --------------------------------------------------------------------------
# insertion planning


def _pool_for(style: str) -> list[str]:
    return {"filler": FILLERS, "offtopic": OFFTOPIC, "restate": RESTATE_FRAMES}[style]


def _fragment(style: str, anchor: dict, toks: list[dict], choice: str) -> dict:
    if style == "restate":
        return {"text": restatement(toks, anchor["span"], choice), "style": style,
                "source": choice, "span": anchor["span"]}
    return {"text": choice, "style": style, "source": choice, "span": None}


def plan_greedy(style: str, toks: list[dict], spans: list[tuple[int, int]],
                target_added: int, seed: int,
                max_per_anchor: int = 8) -> tuple[dict[int, list[dict]], int, dict]:
    """Place insertions until the added word count equals the target.

    Deterministic given (style, target_added, seed).

    Phase 1, bulk. The anchors are shuffled once with random.Random(seed) and
    then swept in that fixed order, up to `max_per_anchor` passes. Each visit
    places one fragment, whose phrase is drawn from an independent stream
    random.Random(seed + 1) and is never a phrase already used at that same
    anchor. A fragment is placed only if it does not overshoot the target.

    Phase 2, fit. The bulk phase stops short of the target by less than the
    length of the next fragment it tried. Phase 2 then searches every
    remaining (anchor, phrase) pair for the single fragment that brings the
    running total closest to the target, and places it. It repeats until no
    candidate improves the gap. Because restatement lengths span roughly 15 to
    60 words and filler phrases span 2 to 5, this lands within a few words.

    An earlier version bisected a per-anchor insertion RATE. That was wrong:
    the phrase draws consume the same random stream as the placement draws, so
    changing the rate reshuffled every later decision and the added-word count
    was not monotone in the rate. Bisection on a non-monotone function got
    stuck 5% away from the target for restate at +25%.
    """
    anchors = anchors_for(style, toks, spans)
    if not anchors:
        raise SystemExit(f"{style}: no anchors")
    pool = _pool_for(style)

    order = list(range(len(anchors)))
    random.Random(seed).shuffle(order)
    prng = random.Random(seed + 1)

    used: dict[int, list[str]] = {}
    placed: dict[int, list[dict]] = {}
    added = 0
    tried_overshoot = 0

    for _pass in range(max_per_anchor):
        if added >= target_added:
            break
        for k in order:
            if added >= target_added:
                break
            a = anchors[k]
            avail = [c for c in pool if c not in used.get(k, [])]
            if not avail:
                continue
            pick = prng.choice(avail)
            frag = _fragment(style, a, toks, pick)
            w = len(frag["text"].split())
            if added + w > target_added:
                tried_overshoot += 1
                continue
            used.setdefault(k, []).append(pick)
            placed.setdefault(a["tok"], []).append(frag)
            added += w

    # Phase 2: close the residual gap with the single best-fitting candidate.
    fit_steps = 0
    while True:
        gap = target_added - added
        if gap <= 0:
            break
        best = None
        for k in order:
            a = anchors[k]
            for c in pool:
                if c in used.get(k, []):
                    continue
                frag = _fragment(style, a, toks, c)
                w = len(frag["text"].split())
                err = abs(gap - w)
                if err >= gap:
                    continue
                if best is None or err < best[0]:
                    best = (err, k, a, frag, w)
        if best is None:
            break
        _, k, a, frag, w = best
        used.setdefault(k, []).append(frag["source"])
        placed.setdefault(a["tok"], []).append(frag)
        added += w
        fit_steps += 1
        if fit_steps > 200:
            break

    stats = {
        "anchors_available": len(anchors),
        "anchors_used": len(placed),
        "fragments": sum(len(v) for v in placed.values()),
        "bulk_overshoot_skips": tried_overshoot,
        "fit_steps": fit_steps,
        "max_fragments_at_one_anchor": max((len(v) for v in placed.values()), default=0),
    }
    return placed, added, stats


def render(toks: list[dict], ins: dict[int, list[dict]]) -> tuple[str, str]:
    """Return (padded_text, recovered_text). recovered must equal the source."""
    padded: list[str] = []
    recovered: list[str] = []
    for i, t in enumerate(toks):
        piece = t["w"] + t["sep"]
        padded.append(piece)
        recovered.append(piece)
        for frag in ins.get(i, []):
            padded.append(frag["text"] + " ")
    return "".join(padded), "".join(recovered)


# --------------------------------------------------------------------------
# timestamps


def retime(text: str, factor: float) -> tuple[str, list[int], list[int]]:
    olds: list[int] = []
    news: list[int] = []

    def sub(m: re.Match) -> str:
        h, mi, s = (int(x) for x in m.group(1, 2, 3))
        t0 = h * 3600 + mi * 60 + s
        t1 = int(round(t0 * factor))
        olds.append(t0)
        news.append(t1)
        return f"[{t1//3600:02d}:{(t1%3600)//60:02d}:{t1%60:02d}]"

    out = re.sub(r"\[(\d\d):(\d\d):(\d\d)\]", sub, text)
    for a, b in zip(news, news[1:]):
        if b <= a:
            raise SystemExit(f"retime produced non-increasing markers: {a} -> {b}")
    return out, olds, news


# --------------------------------------------------------------------------


def build(rec: dict, code: str, style: str, target: float) -> dict:
    src = rec["text"]
    toks = tokenise(src)
    spans = sentence_spans(toks)

    declared = rec["word_count"]
    split_words = len(src.split())
    target_added = int(round(declared * target))

    ins, added, pstats = plan_greedy(style, toks, spans, target_added, SEED)
    padded_raw, recovered = render(toks, ins)

    # Gate 1: additive only.
    if recovered != src:
        raise SystemExit(f"{code}: recovered text differs from source; padding is not additive")

    factor = (split_words + added) / split_words
    padded, olds, news = retime(padded_raw, factor)

    # Gate 2: blinding placeholders untouched. Gate 1 already proves every
    # original occurrence survives byte for byte. What is left to prove is
    # that the padding introduced no NEW kind of bracketed token, and no
    # partially-rewritten placeholder. `restate` copies whole sentences, so a
    # sentence that mentioned [COMPANY] legitimately mentions it twice after
    # restatement; that is repetition, not a blinding change, so the count is
    # allowed to rise for that style only.
    allowed = {"[SUBJECT]", "[COMPANY]"}
    ph_counts = {}
    for frags in ins.values():
        for f in (fr["text"] for fr in frags):
            for tok in re.findall(r"\[[^\]\n]{0,40}\]", f):
                if tok not in allowed:
                    raise SystemExit(f"{code}: padding introduced bracketed token {tok!r}")
                ph_counts[tok] = ph_counts.get(tok, 0) + 1
    for ph in sorted(allowed):
        before, after = src.count(ph), padded.count(ph)
        if after != before + ph_counts.get(ph, 0):
            raise SystemExit(f"{code}: placeholder {ph} accounting failed "
                             f"{before} + {ph_counts.get(ph, 0)} != {after}")
        if style != "restate" and after != before:
            raise SystemExit(f"{code}: style {style} must not duplicate {ph} "
                             f"({before} -> {after})")
    # Gate 3: every inserted fragment is provably contentless.
    #   filler / offtopic : the fragment must be an exact member of the style
    #                       lexicon, and every lexicon entry is asserted at
    #                       import time to carry no digit.
    #   restate           : the fragment must be reproducible, character for
    #                       character, by applying one of the six fixed frames
    #                       to a sentence that is already in the transcript.
    #                       Any number it contains is therefore a verbatim
    #                       copy, never a new figure.
    for frags in ins.values():
        for fr in frags:
            if style in ("filler", "offtopic"):
                pool = FILLERS if style == "filler" else OFFTOPIC
                if fr["text"] not in pool:
                    raise SystemExit(f"{code}: fragment not in lexicon: {fr['text'][:80]}")
            else:
                if fr["source"] not in RESTATE_FRAMES:
                    raise SystemExit(f"{code}: unknown restate frame")
                if restatement(toks, fr["span"], fr["source"]) != fr["text"]:
                    raise SystemExit(f"{code}: restatement is not a verbatim copy of its sentence")
    # Gate 4: markers preserved.
    n_marks = len(re.findall(r"\[\d\d:\d\d:\d\d\]", padded))
    if n_marks != rec["n_timestamp_marks"]:
        raise SystemExit(f"{code}: marker count {n_marks} != {rec['n_timestamp_marks']}")
    # Gate 5: realised inflation on target.
    realised = added / declared
    if abs(realised - target) > TARGET_TOL:
        raise SystemExit(f"{code}: realised inflation {realised:.4f} misses target {target}")

    out = dict(rec)
    out["source_id"] = f"{rec['source_id']}-{code}"
    out["text"] = padded
    out["word_count"] = declared + added
    out["char_count"] = rec["char_count"] + (len(padded) - len(src))
    out["duration_sec"] = int(round(rec["duration_sec"] * factor))
    out["padding"] = {
        "probe": "P1_length_padding",
        "variant_code": code,
        "style": style,
        "target_inflation": target,
        "realised_inflation": round(realised, 5),
        "seed": SEED,
        "planner": pstats,
        "anchors_used": pstats["anchors_used"],
        "fragments_inserted": pstats["fragments"],
        "words_added": added,
        "baseline_source_id": rec["source_id"],
        "baseline_word_count": declared,
        "duration_scale_factor": round(factor, 5),
        "marker_times_before": olds[:5] + ["..."] + olds[-2:],
        "marker_times_after": news[:5] + ["..."] + news[-2:],
        "placeholders_repeated_by_restatement": ph_counts,
        "integrity": {
            "additive_only_byte_exact": True,
            "placeholders_accounted": True,
            "fragments_provably_contentless": True,
            "marker_count_unchanged": True,
        },
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--out", default="data/fixtures_padded")
    ap.add_argument("--manifest", default="data/logs/padding_manifest.json",
                    help="Written OUTSIDE --out on purpose: grade.py picks up transcripts with "
                         "rglob('*.json'), so a manifest sitting in the fixture tree would be "
                         "queued as a seventh transcript and crash on the missing leader_slug.")
    args = ap.parse_args()

    rec = json.loads(Path(args.fixture).read_text())
    outdir = Path(args.out) / rec["leader_slug"]
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "probe": "P1_length_padding",
        "baseline_fixture": args.fixture,
        "baseline": {
            "transcript_id": f"{rec['leader_slug']}/{rec['source_id']}",
            "word_count": rec["word_count"],
            "duration_sec": rec["duration_sec"],
            "n_timestamp_marks": rec["n_timestamp_marks"],
        },
        "seed": SEED,
        "variants": {},
    }

    for code, (style, target) in VARIANTS.items():
        v = build(rec, code, style, target)
        path = outdir / f"{v['source_id']}.json"
        path.write_text(json.dumps(v, ensure_ascii=False, indent=1))
        manifest["variants"][code] = {
            "style": style,
            "target_inflation": target,
            "source_id": v["source_id"],
            "transcript_id": f"{v['leader_slug']}/{v['source_id']}",
            "path": str(path),
            **{k: v["padding"][k] for k in
               ("realised_inflation", "words_added", "fragments_inserted",
                "anchors_used", "duration_scale_factor")},
            "word_count": v["word_count"],
            "duration_sec": v["duration_sec"],
        }
        print(f"{code}  {style:<9} target +{int(target*100)}%  "
              f"added {v['padding']['words_added']:>5} words  "
              f"wc {rec['word_count']} -> {v['word_count']}  "
              f"dur {rec['duration_sec']}s -> {v['duration_sec']}s  "
              f"frags {v['padding']['fragments_inserted']:>4}  "
              f"anchors {v['padding']['anchors_used']:>4}/"
              f"{v['padding']['planner']['anchors_available']}")

    mpath = Path(args.manifest)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"\nmanifest -> {mpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
