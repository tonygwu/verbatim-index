#!/usr/bin/env python3
"""Pure functions shared by the Verbatim Predictions pipeline.

No subprocess, no model call, no argparse. Everything here is deterministic and
testable from a string, which is what lets the driver, the validator, the eval
and the aggregator agree on grounding, ids, dates and the data write guard
without three re-implementations drifting apart.

What lives here:
  - normalisation and exact quote grounding, mapped back to ORIGINAL offsets
  - the stable prediction id and the overlap dedupe rule
  - statement date and the market cutoff rule (never declared_year)
  - the data/ write guard: this clone may write ONLY under data/predictions
  - contract hashes for the three model-facing specs
  - the prompt builders for extraction and verification
  - a small JSON-Schema-subset walker, used on model output and on records
  - the derived booleans (qualifies, agreement, accepted) in one place

The harness callables (call_fable, call_astra, call_gemini) are deliberately
NOT imported here: they live in grade.py and only extract_predictions.py
touches them, so this module and its tests never spawn a process.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402
from grade import (  # noqa: E402
    ALL_ERROR_TYPES as _GRADE_ERROR_TYPES,
    E_BADJSON, E_NOJSON, E_SCHEMA, classify_exception_detail as _classify_grade_detail,
    extract_json, stamp_failure, utcnow,
)

SKILL = REPO / ".claude" / "skills" / "prediction-extractor"
EXTRACTION_SPEC = "EXTRACTION.md"
EXTRACTOR_SCHEMA = "extractor_output.schema.json"
VERIFICATION_SPEC = "VERIFICATION.md"
VERIFIER_SCHEMA = "verifier_output.schema.json"
MATCHING_SPEC = "MATCHING.md"
MATCHER_SCHEMA = "matcher_output.schema.json"
RECORD_SCHEMA = "prediction_record.schema.json"
POLICY_SPEC = "ELIGIBILITY.md"
POLICY_RELEASE_FILE = "POLICY_RELEASE.json"
POLICY_MARKER = "{{ELIGIBILITY_POLICY}}"
# The TRANSCRIPT METADATA block both prompts carry, with one date line per basis.
# It is prompt text outside both specs, so POLICY_RELEASE.json pins it as a third
# hash (rescue round 4, critique 3 B2): a wording change needs a new release.
HEADER_TEMPLATE_FILE = "STATEMENT_DATE_HEADER.json"
HEADER_DATE_LINES = ("stated_in_page", "publication_date", "youtube_upload_date", "unknown", "override_day",
                     "override_range", "own_later", "own_none", "check_day", "check_sourced", "check_unsourced")
# What a stage may say about the date line (release 2.3). Only the first of the
# two doubts holds a record; cannot_tell is recorded and does not.
DOUBT_VALUES = ("none", "recording_older_than_stated", "cannot_tell")
HOLDING_DOUBT = "recording_older_than_stated"
CLAIM_FORMS = ("simple", "conditional", "ordering", "recurring")

# Bounds that appear in the model-facing spec text as well. test_predictions_driver
# asserts the spec states the same numbers, so a change here is a contract change.
MAX_CANDIDATES = 40       # per transcript; the extractor reports cap_hit above this
VERIFY_BATCH = 12         # candidates per verifier call
CONTEXT_WORDS = 400       # each side of the quote, mechanical cut
MIN_QUOTE_WORDS = 8
MAX_QUOTE_WORDS = 60

SCHEMA_VERSION = 1
SENTINEL_RESOLUTION = {"status": "not_started"}
SENTINEL_CONSENSUS = {"status": "not_searched"}
GATES = ("forward_looking", "falsifiable", "committed", "own_voice", "stands_alone")
HARNESSES = ("fable", "astra", "gemini")
PROVIDER_TO_HARNESS = {"claude": "fable", "codex": "astra", "antigravity": "gemini"}

# Failure taxonomy: grade.py's labels plus the ones this pipeline can add.
E_ROUTER = "router_no_account"
E_VERIFIER_SAME = "verifier_same_harness"
E_UNGROUNDED = "quote_not_grounded"
E_TRANSCRIPT_MISSING = "transcript_missing"
E_CACHE_STALE = "cache_stale"
E_POLICY = "policy_release_mismatch"
ALL_ERROR_TYPES = tuple(_GRADE_ERROR_TYPES) + (
    E_ROUTER, E_VERIFIER_SAME, E_UNGROUNDED, E_TRANSCRIPT_MISSING, E_CACHE_STALE, E_POLICY)



def router_version_ok(requirements: "Path | None" = None) -> tuple[bool, str]:
    """Is the installed quota-router new enough to see every configured account?

    A stale venv is silent and expensive. repo-2 ran llm-quota-router 0.1.0
    against a requirements floor of 0.1.1 on 2026-09-14. Under 0.1.0 the fifth
    Claude account was visible to `quotapick status` and to load_config() and
    absent from select_account()'s candidate set, so the driver routed Fable
    work to four spent accounts and burned 31 calls in 21 seconds. Nothing
    caught it, and the wrong bug was reported for an hour.
    """
    req = Path(requirements) if requirements else REPO / "requirements.txt"
    want = None
    for line in req.read_text().splitlines():
        m = re.search(r"llm-quota-router\s*@.*@v([0-9]+(?:\.[0-9]+)*)", line)
        if m:
            want = m.group(1)
            break
    if want is None:
        return False, f"no llm-quota-router version pin found in {req}"
    try:
        import quota_router
        have = getattr(quota_router, "__version__", None)
    except Exception as exc:  # noqa: BLE001 -- absence is the failure we report
        return False, f"quota_router is not importable: {exc}"
    if not have:
        return False, "the installed quota_router declares no __version__"
    def parts(v):
        return tuple(int(x) for x in v.split("."))
    if parts(have) < parts(want):
        return False, (f"quota_router {have} is older than the {want} required by {req.name}; "
                       f"an older router hides configured accounts from select_account(). "
                       f"Fix: uv pip install --python .venv/bin/python -r requirements.txt")
    return True, f"quota_router {have} meets the {want} floor"

def transcript_id_from_path(path) -> str:
    """<leader_slug>/<source_id> from the file's own location.

    A pass lists the corpus once at launch and repo-0 keeps retiring recordings
    under it, so a job may reach a file that no longer exists. The id must be
    knowable without opening the file, or an excluded transcript that has just
    been withdrawn reads as a crash instead of a skip.
    """
    p = Path(path)
    return f"{p.parent.name}/{p.stem}"


def classify_exception_detail(detail: str) -> str:
    hits = [e for e in ALL_ERROR_TYPES if detail.startswith(e)]
    return max(hits, key=len) if hits else _classify_grade_detail(detail)


class RefusedDataWrite(RuntimeError):
    """Raised before any byte is written outside the one allowed data/ subtree."""


class PredictionError(ValueError):
    """A record, response or file that fails a rule. The message names the rule."""


# ---------------------------------------------------------------------------
# Normalisation and grounding
# ---------------------------------------------------------------------------

MARK_RE = re.compile(r"\[(\d{1,2}):(\d{2}):(\d{2})\]")


def mark_seconds(mark: str | None) -> int | None:
    """'[01:02:03]' -> 3723. None or 'unmarked' -> None."""
    if not mark:
        return None
    m = MARK_RE.fullmatch(mark.strip())
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase alphanumerics with single spaces, plus a map back to original offsets.

    Only [hh:mm:ss] timestamp marks are removed; every other bracket token such
    as [Music] is ordinary text on both sides of the comparison. Every
    non-alphanumeric character becomes a space, so straight and curly
    apostrophes, dashes and punctuation all normalise the same way. Runs of
    spaces collapse to one. `map[i]` is the original index of normalised char i.
    """
    out: list[str] = []
    omap: list[int] = []
    pending_space_at: int | None = None
    i = 0
    n = len(text)
    while i < n:
        m = MARK_RE.match(text, i)
        if m:
            if out and pending_space_at is None:
                pending_space_at = i
            i = m.end()
            continue
        ch = text[i]
        if ch.isalnum():
            if pending_space_at is not None:
                out.append(" ")
                omap.append(pending_space_at)
                pending_space_at = None
            low = ch.lower()
            if len(low) != 1:  # a few code points lowercase to two chars; keep alignment
                low = ch
            out.append(low)
            omap.append(i)
        else:
            if out and pending_space_at is None:
                pending_space_at = i
        i += 1
    return "".join(out), omap


def normalise(text: str) -> str:
    return normalise_with_map(text)[0]


def _find_all(hay: str, needle: str) -> list[int]:
    """Start offsets of every match of needle in hay, on word boundaries, non-overlapping."""
    hits = []
    start = 0
    while True:
        k = hay.find(needle, start)
        if k < 0:
            return hits
        left_ok = k == 0 or hay[k - 1] == " "
        right = k + len(needle)
        right_ok = right == len(hay) or hay[right] == " "
        if left_ok and right_ok:
            hits.append(k)
        start = k + 1


def nearest_mark(text: str, start: int) -> str:
    """The last [hh:mm:ss] mark that begins at or before `start`, else 'unmarked'."""
    best = None
    for m in MARK_RE.finditer(text):
        if m.start() <= start:
            best = m.group(0)
        else:
            break
    return best or "unmarked"


def locate_quote(text: str, quote: str, timestamp_hint: str | None = None) -> dict:
    """Ground a model-written quote in the original transcript, exactly.

    Returns {"start", "end", "occurrences"} with offsets into the ORIGINAL text,
    or {"error": reason, "occurrences": n}. Reasons: empty_quote, not_found,
    ambiguous_no_hint. There is deliberately no fuzzy fallback: a quote that
    does not match after normalisation is not a verbatim quote.

    When the normalised quote occurs more than once, `timestamp_hint` (the
    mark the model said was nearest) picks the occurrence whose nearest mark
    is that hint, if exactly one occurrence has it.
    """
    nq = normalise(quote)
    if not nq:
        return {"error": "empty_quote", "occurrences": 0}
    ntext, omap = normalise_with_map(text)
    hits = _find_all(ntext, nq)
    if not hits:
        return {"error": "not_found", "occurrences": 0}

    def to_original(k: int) -> tuple[int, int]:
        return omap[k], omap[k + len(nq) - 1] + 1

    if len(hits) == 1:
        s, e = to_original(hits[0])
        return {"start": s, "end": e, "occurrences": 1}
    if timestamp_hint and MARK_RE.fullmatch(timestamp_hint.strip()):
        want = timestamp_hint.strip()
        matching = [k for k in hits if nearest_mark(text, to_original(k)[0]) == want]
        if len(matching) == 1:
            s, e = to_original(matching[0])
            return {"start": s, "end": e, "occurrences": len(hits)}
    return {"error": "ambiguous_no_hint", "occurrences": len(hits)}


_TOKEN_RE = re.compile(r"\S+")


def quote_word_count(s: str) -> int:
    return len(_TOKEN_RE.findall(MARK_RE.sub(" ", s)))


def context_window(text: str, start: int, end: int, words: int = CONTEXT_WORDS) -> tuple[str, str]:
    """Up to `words` whitespace tokens before `start` and after `end`, snapped to token edges.

    Marks stay in the window text: a reader wants to see them, and the verifier
    is told what they are. The cut is mechanical so the validator can recompute it.
    """
    before_tokens = list(_TOKEN_RE.finditer(text, 0, start))
    before = text[before_tokens[max(0, len(before_tokens) - words)].start():start] if before_tokens else ""
    after_tokens = []
    for m in _TOKEN_RE.finditer(text, end):
        after_tokens.append(m)
        if len(after_tokens) >= words:
            break
    after = text[end:after_tokens[-1].end()] if after_tokens else ""
    return before.strip(), after.strip()


# ---------------------------------------------------------------------------
# Ids, ordering, dedupe
# ---------------------------------------------------------------------------

def prediction_id(transcript_id: str, quote: str) -> str:
    """sha256 of the transcript id and the NORMALISED quote, 16 hex chars.

    Offsets are excluded on purpose: a re-repaired transcript shifts every
    offset and leaves the quote intact, and the id should survive that.
    """
    return hashlib.sha256(f"{transcript_id}\n{normalise(quote)}".encode("utf-8")).hexdigest()[:16]


def record_sort_key(rec: dict) -> tuple[int, str]:
    return rec["source"]["quote_char_start"], rec["prediction_id"]


DEDUPE_OVERLAP = 0.8   # share of the LONGER span that the two spans share before they count as one


def span_overlap(a: dict, b: dict) -> float:
    """Shared characters as a share of the longer span. 0 when disjoint, 1 when identical."""
    shared = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    longer = max(a["end"] - a["start"], b["end"] - b["start"], 1)
    return shared / longer


def dedupe_overlapping(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse NEAR-IDENTICAL spans within one transcript, and nothing else.

    Two candidates are one prediction only when they share at least
    DEDUPE_OVERLAP of the longer span: the same sentence quoted with slightly
    different boundaries. Merely overlapping spans are two records, because two
    distinct claims can share words. FOUND on the first live transcript
    (george-hotz/mapbox-n9wxlr, 2026-09-10): a rule that collapsed any overlap
    kept "we are going to be better than GM supercruise" and silently dropped
    "we are going to open source all the highway maps by the end of the year",
    which sat inside the same 39-word span.

    Among near-identical spans keep the longer; tie on the smaller start; tie
    on the smaller id. Dropped entries are returned with `kept_by`, never lost.
    """
    order = sorted(cands, key=lambda c: (-(c["end"] - c["start"]), c["start"], c["prediction_id"]))
    kept: list[dict] = []
    dropped: list[dict] = []
    for c in order:
        clash = next((k for k in kept if span_overlap(c, k) >= DEDUPE_OVERLAP), None)
        if clash is None:
            kept.append(c)
        else:
            dropped.append({"prediction_id": c["prediction_id"], "start": c["start"], "end": c["end"],
                            "kept_by": clash["prediction_id"]})
    kept.sort(key=lambda c: (c["start"], c["prediction_id"]))
    return kept, dropped


# ---------------------------------------------------------------------------
# Dates and the market cutoff
# ---------------------------------------------------------------------------

# Bases a transcript record may declare for its own statement date. Each says
# how the date relates to the moment of speech, because that is what a horizon
# is measured from.
#   stated_in_page    the source itself states when the words were spoken; exact
#   publication_date  the date the source was published; an UPPER BOUND on speech
#   youtube_upload_date  the upload date; an upper bound. Derived, never declared.
# A fourth basis, `sourced_override` (OVERRIDE_DATE_BASIS below), is never declared
# by a transcript either: it comes from the reviewed override file.
DECLARED_DATE_BASES = {"stated_in_page", "publication_date"}


def own_statement_date(rec: dict) -> tuple[str | None, str]:
    """(YYYY-MM-DD, basis) from the transcript alone, ignoring any override.

    declared_year is never consulted.

    A transcript may DECLARE `statement_date` with a `statement_date_basis`, for
    a source that is not a YouTube recording and has no upload date. Otherwise
    the date comes from `yt_upload_date` as before, so every existing transcript
    is unaffected.

    A malformed date raises: guessing one would put a wrong 'said on' next to a
    quote and silently poison every horizon computed from it. That is not
    hypothetical here. A `or 2024` default once reached every judge on every
    grade for four days.
    """
    declared = rec.get("statement_date")
    if declared not in (None, ""):
        basis = rec.get("statement_date_basis")
        if basis not in DECLARED_DATE_BASES:
            raise PredictionError(
                f"statement_date: {rec.get('source_id')} declares statement_date "
                f"{declared!r} with basis {basis!r}; must be one of "
                f"{sorted(DECLARED_DATE_BASES)}")
        if not isinstance(declared, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", declared):
            raise PredictionError(
                f"statement_date: declared statement_date {declared!r} is not "
                f"YYYY-MM-DD in {rec.get('source_id')}")
        try:
            datetime.strptime(declared, "%Y-%m-%d")
        except ValueError as exc:
            raise PredictionError(
                f"statement_date: declared statement_date {declared!r} is not a "
                f"real date in {rec.get('source_id')}: {exc}") from exc
        if rec.get("yt_upload_date"):
            raise PredictionError(
                f"statement_date: {rec.get('source_id')} carries BOTH a declared "
                f"statement_date and a yt_upload_date; exactly one source of "
                f"truth, or the basis recorded on the record is not the one used")
        return declared, basis
    raw = rec.get("yt_upload_date")
    if raw in (None, ""):
        return None, "unknown"
    if not isinstance(raw, str) or not re.fullmatch(r"\d{8}", raw):
        raise PredictionError(f"statement_date: yt_upload_date {raw!r} is not YYYYMMDD in {rec.get('source_id')}")
    try:
        d = datetime.strptime(raw, "%Y%m%d")
    except ValueError as exc:
        raise PredictionError(f"statement_date: yt_upload_date {raw!r} is not a real date: {exc}") from exc
    return d.strftime("%Y-%m-%d"), "youtube_upload_date"



# ---------------------------------------------------------------------------
# Sourced statement-date overrides (VP-16)
# ---------------------------------------------------------------------------
#
# An upload date is an UPPER bound on when the words were said, and on an old
# recording it is decades late. FOUND 2026-09-27: 13 past-due records carried a
# deadline computed from an upload date, 11 of them resolved
# `deadline_incoherent`. Netscape's 1996-10-16 keynote, uploaded 2013-07-05,
# became "Netscape will create a network of online marketplaces by approximately
# September 2013": the extractor read "the next couple months" against the date it
# was given. So the correction cannot be a date swap on the finished record. The
# claim text and the target date embed the wrong year, and the transcript must be
# re-extracted under the true date.
#
# The override is keyed by TRANSCRIPT, because the date is a property of the
# recording and every prediction from it inherits the date. It is applied at ONE
# point, `apply_statement_date_override`, when a transcript is read for
# extraction, so the prompt header, the record, the funnel's deadline and both
# Phase 2 prompts all read the same date. The transcript file itself is never
# rewritten: it is the fetcher's faithful record of what YouTube reported, and it
# belongs to the daemon clone.

OVERRIDE_DATE_BASIS = "sourced_override"
# Relative to the data root. Production keeps the reviewed file here; an
# experiment passes its own with --date-overrides. It sits under predictions/,
# which ownership.json makes shared, so any contributor clone can commit it;
# sources/ is daemon-only.
DATE_OVERRIDES_FILE = Path("predictions") / "statement_date_overrides.json"
TRANSCRIPT_DIRS = ("transcripts_open", "transcripts_web")
OVERRIDE_REQUIRED = ("statement_date", "basis", "source_url", "verbatim_evidence", "confirmed_by", "confirmed_at_utc")
OVERRIDE_OPTIONAL = ("internal_evidence", "confidence", "confirmation_note", "researched_by", "speaker_check",
                     # A range: the first day the words could have been spoken, with
                     # statement_date as the last (design D1: the latest day).
                     "statement_date_earliest", "precision", "earliest_evidenced",
                     # An entry the dating stage wrote: how it was confirmed, re-checked on load.
                     "confirmation")
# Who may confirm an entry. An operator entry is taken on the operator's word; an
# agent entry must carry its confirmation and is re-verified from it on every load.
AGENT_CONFIRMATION = "agent_plus_source_check"
PRECISIONS = ("day", "days", "months", "years")
_UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _strict_date(value, where: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PredictionError(f"statement_date_override: {where}: statement_date {value!r} is not YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise PredictionError(f"statement_date_override: {where}: statement_date {value!r} is not a real date: {exc}") from exc
    return value


def date_precision(earliest: str, latest: str) -> str:
    """How wide a range of days is, in words a reader can check: DERIVED, never chosen."""
    span = (datetime.strptime(latest, "%Y-%m-%d") - datetime.strptime(earliest, "%Y-%m-%d")).days
    if span < 0:
        raise PredictionError(f"statement_date_override: earliest {earliest} is after latest {latest}")
    return "day" if span == 0 else "days" if span <= 31 else "months" if span <= 366 else "years"


def check_override_entry(tid: str, entry) -> dict:
    """Refuse an entry that cannot vouch for itself. Returns a copy."""
    if not isinstance(tid, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", tid):
        raise PredictionError(f"statement_date_override: key {tid!r} is not a transcript id of the form slug/source")
    if not isinstance(entry, dict):
        raise PredictionError(f"statement_date_override: {tid}: entry is {type(entry).__name__}, not an object")
    missing = [k for k in OVERRIDE_REQUIRED if k not in entry]
    unknown = sorted(set(entry) - set(OVERRIDE_REQUIRED) - set(OVERRIDE_OPTIONAL))
    if missing or unknown:
        raise PredictionError(f"statement_date_override: {tid}: missing {missing}, unknown {unknown}; an entry "
                              f"carries {list(OVERRIDE_REQUIRED)} and optionally {list(OVERRIDE_OPTIONAL)}")
    _strict_date(entry["statement_date"], tid)
    for k in ("basis", "source_url", "verbatim_evidence", "confirmed_by"):
        if not isinstance(entry[k], str) or not entry[k].strip():
            raise PredictionError(f"statement_date_override: {tid}: {k} is empty")
    if not re.match(r"https?://", entry["source_url"]):
        raise PredictionError(f"statement_date_override: {tid}: source_url {entry['source_url']!r} is not http(s)")
    if not isinstance(entry["confirmed_at_utc"], str) or not _UTC_STAMP.fullmatch(entry["confirmed_at_utc"]):
        raise PredictionError(f"statement_date_override: {tid}: confirmed_at_utc {entry['confirmed_at_utc']!r} "
                              f"is not YYYY-MM-DDTHH:MM:SSZ")
    if ("statement_date_earliest" in entry) != ("precision" in entry):
        raise PredictionError(f"statement_date_override: {tid}: statement_date_earliest and precision travel together")
    if "statement_date_earliest" in entry:
        _strict_date(entry["statement_date_earliest"], f"{tid} statement_date_earliest")
        want = date_precision(entry["statement_date_earliest"], entry["statement_date"])
        if entry["precision"] != want:
            raise PredictionError(f"statement_date_override: {tid}: precision {entry['precision']!r} is not the "
                                  f"span's own, {want!r}")
    if "earliest_evidenced" in entry and not isinstance(entry["earliest_evidenced"], bool):
        raise PredictionError(f"statement_date_override: {tid}: earliest_evidenced must be true or false")
    if (entry["confirmed_by"] == AGENT_CONFIRMATION) != ("confirmation" in entry):
        raise PredictionError(f"statement_date_override: {tid}: an entry is confirmed_by {AGENT_CONFIRMATION!r} "
                              f"exactly when it carries a confirmation block; confirmed_by is "
                              f"{entry['confirmed_by']!r}")
    return dict(entry)


def check_override_against_transcript(tid: str, date: str, rec: dict) -> tuple[str | None, str]:
    """(own date, own basis) of the transcript, after refusing an override it contradicts.

    An upload or a publication cannot precede the speech, so an override dated
    AFTER the transcript's own date is refused. A page that STATES its own date is
    not overridden at all: its date is a fact about the words, not a bound.
    """
    own_date, own_basis = own_statement_date(rec)
    if own_basis == "stated_in_page":
        raise PredictionError(f"statement_date_override: {tid}: the source states its own date "
                              f"({own_date}, stated_in_page); an override may not contradict it")
    if own_date is not None and date > own_date:
        raise PredictionError(f"statement_date_override: {tid}: override date {date} is after the "
                              f"{own_basis} {own_date}; a recording cannot be published before it is spoken")
    return own_date, own_basis


def load_statement_date_overrides(path, transcript_roots) -> dict[str, dict]:
    """{transcript_id: entry} from a reviewed override file, or raise.

    Every entry must name a transcript present under one of `transcript_roots`
    and must not post-date that transcript's own date. Nothing is skipped: an
    entry that cannot be applied stops the run, naming it.
    """
    path = Path(path)
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("overrides"), dict) \
            or set(doc) - {"schema_version", "overrides", "notes"}:
        raise PredictionError(f"statement_date_override: {path} must be "
                              f'{{"schema_version": 1, "overrides": {{transcript_id: entry}}}} (optional "notes")')
    roots = [Path(r) for r in transcript_roots]
    out: dict[str, dict] = {}
    for tid, entry in doc["overrides"].items():
        e = check_override_entry(tid, entry)
        slug, sid = tid.split("/", 1)
        hits = [r / slug / f"{sid}.json" for r in roots if (r / slug / f"{sid}.json").is_file()]
        if not hits:
            raise PredictionError(f"statement_date_override: {tid}: unknown transcript; not under any of "
                                  f"{[str(r) for r in roots]}")
        for h in hits:
            trec = json.loads(h.read_text())
            check_override_against_transcript(tid, e["statement_date"], trec)
            if e["confirmed_by"] == AGENT_CONFIRMATION:
                # An agent entry vouches for itself from what it stored: the proposal
                # file by sha256, and each confirming page by the window kept around its
                # excerpt. Re-checked here, in every stage that loads the file, so an
                # entry that cannot vouch for itself stops the run rather than a date.
                import dating_lib  # noqa: PLC0415 -- dating_lib imports this module
                dating_lib.verify_agent_entry(tid, e, trec, path)
        out[tid] = e
    return out


def date_overrides_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apply_statement_date_override(rec: dict, overrides: dict | None) -> dict:
    """The transcript as the predictions pipeline must read it. The single point of entry.

    A transcript with no entry is returned as the SAME object, so every existing
    record, prompt and hash is unchanged.
    """
    if not overrides:
        return rec
    tid = f"{rec.get('leader_slug')}/{rec.get('source_id')}"
    entry = overrides.get(tid)
    if entry is None:
        return rec
    check_override_against_transcript(tid, _strict_date(entry["statement_date"], tid), rec)
    return {**rec, "statement_date_override": dict(entry)}


def derive_statement_date(rec: dict) -> tuple[str | None, str]:
    """(YYYY-MM-DD, basis). An applied override wins; otherwise the transcript's own date.

    The override is re-checked here as well as at load, so a record can never
    carry a date later than its own upload whichever path built it.
    """
    ov = rec.get("statement_date_override")
    if ov is None:
        return own_statement_date(rec)
    tid = f"{rec.get('leader_slug')}/{rec.get('source_id')}"
    date = _strict_date((ov or {}).get("statement_date"), tid)
    check_override_against_transcript(tid, date, rec)
    return date, OVERRIDE_DATE_BASIS


def override_block(rec: dict) -> dict | None:
    """What a record carries about its override: the evidence, and what it replaced."""
    ov = rec.get("statement_date_override")
    if ov is None:
        return None
    own_date, own_basis = own_statement_date(rec)
    # The range fields travel only when the entry has them, so a record built from
    # an entry without them (the operator's Andreessen entry) is byte-identical.
    return {"basis": ov["basis"], "source_url": ov["source_url"], "verbatim_evidence": ov["verbatim_evidence"],
            "confirmed_by": ov["confirmed_by"], "confirmed_at_utc": ov["confirmed_at_utc"],
            "replaced_date": own_date, "replaced_basis": own_basis,
            **{k: ov[k] for k in ("statement_date_earliest", "precision", "earliest_evidenced") if k in ov}}


DATE_ONLY_RULE = ("cutoff is 00:00:00 UTC at the start of the publication date, so every observation "
                  "taken before it precedes the upload whatever time of day the upload happened; "
                  "precision is date-level and staleness may reach 24 hours")


def publication_cutoff(rec_or_record: dict) -> dict:
    """The instant strictly before which a market observation counts as ex-ante.

    Accepts a transcript record (with yt_upload_date) or a prediction record
    (with source.statement_date). Only the date-only basis exists in this corpus;
    the timestamp bases are reserved and returned when a future field carries one.
    """
    src = rec_or_record.get("source") if isinstance(rec_or_record.get("source"), dict) else None
    if src is not None:
        date, basis = src.get("statement_date"), src.get("statement_date_basis")
        if basis == "unknown" or not date:
            date = None
    else:
        date, basis = derive_statement_date(rec_or_record)
    if date is None:
        return {"basis": "unknown", "requested_cutoff_utc": None, "precision": "none",
                "rule": "no statement date on the record; no observation can be shown to be ex-ante"}
    return {"basis": "publication_date_only", "requested_cutoff_utc": f"{date}T00:00:00Z",
            "precision": "date", "rule": DATE_ONLY_RULE}


TARGET_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def target_date_valid(s: str | None) -> bool:
    if s is None:
        return True
    if not isinstance(s, str) or not TARGET_DATE_RE.match(s):
        return False
    fmt = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}[len(s)]
    try:
        datetime.strptime(s, fmt)
        return True
    except ValueError:
        return False


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# The data/ write guard
# ---------------------------------------------------------------------------

def data_root() -> Path:
    return (REPO / "data").resolve()


def guard_data_path(path: str | Path, root: Path | None = None) -> Path:
    """Refuse any write under data/ that is not under data/predictions.

    repo-0 owns everything else under data/ (AGENTS.md, clone roles). This is
    checked on the RESOLVED path so `data/predictions/../grades` is refused too.
    Paths outside data/ entirely (tempdirs in tests) pass through.
    """
    explicit_root = root is not None
    root = (root or data_root()).resolve()
    if not explicit_root:
        from data_clone_workflow import guard_prediction_write
        try:
            guard_prediction_write(REPO, Path(path), root)
        except RuntimeError as exc:
            raise RefusedDataWrite(f"refusing to write {path}: {exc}") from exc
    allowed = root / "predictions"
    p = Path(path).resolve()
    if p == root or root in p.parents:
        if not (p == allowed or allowed in p.parents):
            raise RefusedDataWrite(f"refusing to write {p}: this clone may write only under {allowed}")
    return p


def write_prediction_file(path: str | Path, text: str, root: Path | None = None) -> Path:
    return write_atomic(guard_data_path(path, root), text)


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

def load_exclusions(path: str | Path) -> dict[str, dict]:
    """transcript_id -> entry. Fails loud on a malformed file rather than excluding nothing."""
    d = json.loads(Path(path).read_text())
    if d.get("schema_version") != 1:
        raise PredictionError(f"exclusions: schema_version {d.get('schema_version')!r} != 1 in {path}")
    out: dict[str, dict] = {}
    for i, e in enumerate(d.get("exclusions", [])):
        for k in ("transcript_id", "reason", "evidence"):
            if not e.get(k):
                raise PredictionError(f"exclusions: entry {i} lacks {k} in {path}")
        if "/" not in e["transcript_id"]:
            raise PredictionError(f"exclusions: entry {i} transcript_id {e['transcript_id']!r} is not slug/source_id")
        out[e["transcript_id"]] = e
    return out


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

def read_spec(spec_path: Path) -> str:
    """Expand the shared policy before hashing AND before constructing a prompt.

    Historical specs without the marker retain their original contract hashes.
    """
    text = spec_path.read_text()
    if POLICY_MARKER not in text:
        return text
    if text.count(POLICY_MARKER) != 1:
        raise PredictionError(f"{E_POLICY}: {spec_path} must include the shared policy exactly once")
    return text.replace(POLICY_MARKER, (spec_path.parent / POLICY_SPEC).read_text())


def json_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def load_policy_release(skill_dir: Path = SKILL) -> dict:
    """A named release pins one compatible pair and the header template; edits require an explicit new pin."""
    path = skill_dir / POLICY_RELEASE_FILE
    release = json.loads(path.read_text())
    actual = {"extract": extraction_contract(skill_dir)["contract_id"],
              "verify": verification_contract(skill_dir)["contract_id"],
              "header": header_contract(skill_dir)["contract_id"]}
    if not isinstance(release.get("release"), str) or not release["release"].strip():
        raise PredictionError(f"{E_POLICY}: {path} has no release name")
    if release.get("contracts") != actual:
        raise PredictionError(f"{E_POLICY}: {path} pins {release.get('contracts')}, files yield {actual}")
    return release


def _contract(spec_path: Path, schema_path: Path) -> dict:
    """Same shape as grade.grading_contract: the pair of files a model sees, hashed together."""
    sb = read_spec(spec_path).encode()
    jb = schema_path.read_bytes()
    return {
        "contract_id": hashlib.sha256(sb + jb).hexdigest()[:12],
        "spec_sha256": hashlib.sha256(sb).hexdigest(),
        "schema_sha256": hashlib.sha256(jb).hexdigest(),
        "spec_bytes": len(sb),
        "schema_bytes": len(jb),
        "spec_file": spec_path.name,
        "schema_file": schema_path.name,
    }


def extraction_contract(skill_dir: Path = SKILL) -> dict:
    return _contract(skill_dir / EXTRACTION_SPEC, skill_dir / EXTRACTOR_SCHEMA)


def verification_contract(skill_dir: Path = SKILL) -> dict:
    return _contract(skill_dir / VERIFICATION_SPEC, skill_dir / VERIFIER_SCHEMA)


def matching_contract(skill_dir: Path = SKILL) -> dict:
    return _contract(skill_dir / MATCHING_SPEC, skill_dir / MATCHER_SCHEMA)


def header_contract(skill_dir: Path = SKILL) -> dict:
    """The header template's bytes, hashed. Pinned in POLICY_RELEASE.json as contracts.header."""
    b = (Path(skill_dir) / HEADER_TEMPLATE_FILE).read_bytes()
    return {"contract_id": hashlib.sha256(b).hexdigest()[:12], "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b), "file": HEADER_TEMPLATE_FILE}


def load_header_template(skill_dir: Path = SKILL) -> dict:
    """The header template, or raise naming what is missing. Never a default line."""
    path = Path(skill_dir) / HEADER_TEMPLATE_FILE
    t = json.loads(path.read_text())
    if not isinstance(t, dict) or t.get("schema_version") != 1 or not isinstance(t.get("header"), str) \
            or "{date_line}" not in t["header"] or not isinstance(t.get("date_lines"), dict) \
            or not isinstance(t.get("own_basis_labels"), dict):
        raise PredictionError(f"header template: {path} must carry schema_version 1, a header with "
                              f"{{date_line}}, date_lines and own_basis_labels")
    missing = [k for k in HEADER_DATE_LINES if not isinstance(t["date_lines"].get(k), str)]
    unknown = sorted(set(t["date_lines"]) - set(HEADER_DATE_LINES))
    if missing or unknown:
        raise PredictionError(f"header template: {path} date_lines missing {missing}, unknown {unknown}")
    return t


def load_record_schema(skill_dir: Path = SKILL) -> dict:
    return json.loads((skill_dir / RECORD_SCHEMA).read_text())


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

NO_SPEAKER_LABELS = (
    "This transcript came from automatic speech recognition. It has no speaker labels, so an\n"
    "interview runs the questions and answers together. Work out from context which turns belong\n"
    "to the subject. When you cannot tell whether the subject or someone else said a sentence, it is\n"
    "NOT the subject's. Proper nouns are frequently corrupted; read through the corruption. Timestamps\n"
    "appear as [hh:mm:ss] markers roughly every minute; other bracket tokens such as [Music] are\n"
    "ordinary caption text."
)


_DEFAULT_HEADER: dict | None = None


def statement_date_line(rec: dict, template: dict) -> str:
    """The one line that says what the statement date is and HOW it is known (design 2.1).

    Every date that was not an override used to reach the extractor as a "YouTube
    upload date", a shareholder letter's printed date included. Each basis now has
    its own line, and an unchecked upload or publication date says it is only an
    upper bound, which is what EXTRACTION.md section 1a tells the extractor to read.
    An override whose date IS the transcript's own date confirms that bound, so it
    reads as a check rather than a correction.
    """
    lines = template["date_lines"]
    date, basis = derive_statement_date(rec)
    if basis != OVERRIDE_DATE_BASIS:
        if basis not in lines:
            raise PredictionError(f"header: no date line for basis {basis!r}")
        return lines[basis].format(date=date)
    ov = rec["statement_date_override"]
    own_date, own_basis = own_statement_date(rec)
    earliest = ov.get("statement_date_earliest") or date
    fields = {"date": date, "earliest": earliest, "basis": ov["basis"],
              "days": (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(earliest, "%Y-%m-%d")).days}
    if own_date is not None and own_basis not in template["own_basis_labels"]:
        raise PredictionError(f"header: no label for the transcript's own basis {own_basis!r}")
    if own_date is not None and own_date == date:
        fields["own_label"] = template["own_basis_labels"][own_basis]
        if earliest == date:
            return lines["check_day"].format(**fields)
        if "earliest_evidenced" not in ov:
            raise PredictionError(f"header: {rec.get('leader_slug')}/{rec.get('source_id')}: an override on the "
                                  f"transcript's own date with a range must say whether a source shows its first "
                                  f"day (earliest_evidenced)")
        return lines["check_sourced" if ov["earliest_evidenced"] else "check_unsourced"].format(**fields)
    own_sentence = (lines["own_none"] if own_date is None else
                    lines["own_later"].format(own_label=template["own_basis_labels"][own_basis], own_date=own_date))
    return lines["override_day" if earliest == date else "override_range"].format(own_sentence=own_sentence, **fields)


def speaker_header(rec: dict, roster_entry: dict | None, template: dict | None = None) -> str:
    """Never declared_year (a hardcoded constant), never today's date (invites resolution reasoning).

    `template` is the pinned STATEMENT_DATE_HEADER.json; the default is the one in
    SKILL. The driver passes the one from --skill-dir, the same directory the
    policy release was checked against.
    """
    global _DEFAULT_HEADER
    if template is None:
        if _DEFAULT_HEADER is None:
            _DEFAULT_HEADER = load_header_template(SKILL)
        template = _DEFAULT_HEADER
    return template["header"].format(
        name=(roster_entry or {}).get("name") or rec["leader_slug"].replace("-", " ").title(),
        role=(roster_entry or {}).get("role") or "unknown",
        company=(roster_entry or {}).get("company") or "unknown",
        sector=(roster_entry or {}).get("sector") or "unknown",
        title=rec.get("yt_title") or rec.get("declared_title") or "unknown",
        venue=rec.get("declared_venue") or "unknown",
        format=rec.get("declared_kind") or "unknown",
        date_line=statement_date_line(rec, template),
        word_count=rec.get("word_count"),
        minutes=round((rec.get("duration_sec") or 0) / 60),
    )


def build_extraction_prompt(rec: dict, roster_entry: dict | None, spec: str, schema: str,
                            header_template: dict | None = None) -> str:
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    return f"""You extract forward-looking, falsifiable predictions that a named speaker made in one public
recording. Apply the specification below to the whole transcript and return one JSON object.

=========================== EXTRACTION SPEC ===========================
{spec}
======================== END EXTRACTION SPEC ==========================

TRANSCRIPT METADATA
{speaker_header(rec, roster_entry, header_template)}
{NO_SPEAKER_LABELS}

=========================== TRANSCRIPT ===========================
{rec['text']}
======================== END TRANSCRIPT ==========================

Return ONE JSON object and nothing else. No preamble, no markdown fences, no commentary.
It must validate against this schema:

{schema}

Requirements that are checked automatically and will cause a candidate or the whole output to be rejected:
- transcript_id must be exactly: {tid}
- Every quote is one contiguous verbatim span of the transcript, {MIN_QUOTE_WORDS} to {MAX_QUOTE_WORDS} words, copied
  character for character. It is matched mechanically against the transcript; a quote that does
  not match is discarded, so prefer a shorter exact span to a longer paraphrase.
- At most {MAX_CANDIDATES} candidates. If more qualify, keep the {MAX_CANDIDATES} most specific, set cap_hit true and
  estimate the true total in estimated_total_qualifying.
- Every candidate carries all five gate booleans and a non-empty resolution_criteria. Return only
  candidates for which every gate is true.
- confidence.probability is a number ONLY when the speaker stated a number, percentage or odds,
  and verbatim_confidence_language then contains those words. Never translate words into a number.
- Do not judge whether any prediction came true. Nothing about outcomes belongs in this output."""


def build_verification_prompt(bundle: dict, spec: str, schema: str) -> str:
    """bundle = {"header": str, "transcript_id": str, "candidates": [{prediction_id, quote_original,
    normalized_claim, timestamp_mark, context_before, context_after}]}. The extractor's gates and
    reasoning are deliberately absent: the verifier must reach its own verdict."""
    parts = []
    for c in bundle["candidates"]:
        parts.append(
            f"--- CANDIDATE {c['prediction_id']} (nearest mark {c['timestamp_mark']}) ---\n"
            f"CONTEXT BEFORE:\n{c['context_before']}\n\n"
            f"QUOTE:\n{c['quote_original']}\n\n"
            f"CONTEXT AFTER:\n{c['context_after']}\n\n"
            f"EXTRACTOR CLAIM:\n{c['normalized_claim']}\n"
        )
    ids = " ".join(c["prediction_id"] for c in bundle["candidates"])
    return f"""You are the second, independent judge of candidate predictions another model extracted from a
transcript. For each candidate you see only a mechanically cut window of the transcript around the
quote and the extractor's one-sentence claim. Apply the specification and return one JSON object.

=========================== VERIFICATION SPEC ===========================
{spec}
======================== END VERIFICATION SPEC ==========================

TRANSCRIPT METADATA
{bundle['header']}
{NO_SPEAKER_LABELS}

=========================== CANDIDATES ===========================
{chr(10).join(parts)}
======================== END CANDIDATES ==========================

Return ONE JSON object and nothing else. No preamble, no markdown fences, no commentary.
It must validate against this schema:

{schema}

Requirements that are checked automatically and will cause your output to be rejected:
- transcript_id must be exactly: {bundle['transcript_id']}
- verdicts must contain exactly one entry for each of these ids, and no others: {ids}
- Every verdict carries all five gate booleans, an attribution, claim_faithful, qualifies, and a
  non-empty resolution_criteria written in your own words.
- Do not judge whether any prediction came true. Nothing about outcomes belongs in this output."""


# ---------------------------------------------------------------------------
# JSON-Schema subset walker
# ---------------------------------------------------------------------------

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(v, t: str) -> bool:
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def check_schema(obj, schema: dict, path: str = "$", root: dict | None = None) -> list[str]:
    """Validate against the subset of JSON Schema this repo's schemas use.

    Supported: type (incl. lists), const, enum, required, properties,
    additionalProperties (false only), items, minimum, maximum, minLength,
    maxLength, anyOf, $ref to #/$defs/<name>. Anything else in a schema is
    an error here, not silently ignored: a keyword the walker skips would make
    a schema look enforced when it is not.
    """
    root = root if root is not None else schema
    errs: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            return [f"{path}: unsupported $ref {ref}"]
        return check_schema(obj, root["$defs"][ref[len("#/$defs/"):]], path, root)
    known = {"$schema", "title", "description", "type", "const", "enum", "required", "properties",
             "additionalProperties", "items", "minimum", "maximum", "minLength", "maxLength",
             "anyOf", "$defs"}
    unknown = set(schema) - known
    if unknown:
        return [f"{path}: schema uses unsupported keywords {sorted(unknown)}"]
    if "anyOf" in schema:
        branches = [check_schema(obj, s, path, root) for s in schema["anyOf"]]
        if not any(len(b) == 0 for b in branches):
            # Report the branch that got DEEPEST before failing: a null branch fails
            # at the top in one step and says nothing useful about a real object.
            best = max(branches, key=lambda b: max((len(e.split(':')[0]) for e in b), default=0))
            return [f"{path}: matches no anyOf branch; closest: {best[0] if best else '?'}"]
        return []
    if "const" in schema and obj != schema["const"]:
        return [f"{path}: expected const {schema['const']!r}, got {obj!r}"]
    if "enum" in schema and obj not in schema["enum"]:
        return [f"{path}: {obj!r} not in enum {schema['enum']}"]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(obj, t) for t in types):
            return [f"{path}: expected type {types}, got {type(obj).__name__}"]
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            errs.append(f"{path}: {obj} < minimum {schema['minimum']}")
        if "maximum" in schema and obj > schema["maximum"]:
            errs.append(f"{path}: {obj} > maximum {schema['maximum']}")
    if isinstance(obj, str):
        if "minLength" in schema and len(obj) < schema["minLength"]:
            errs.append(f"{path}: length {len(obj)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(obj) > schema["maxLength"]:
            errs.append(f"{path}: length {len(obj)} > maxLength {schema['maxLength']}")
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{path}: missing required {k}")
        props = schema.get("properties", {})
        for k, v in obj.items():
            if k in props:
                errs.extend(check_schema(v, props[k], f"{path}.{k}", root))
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property {k}")
    if isinstance(obj, list) and "items" in schema:
        for i, v in enumerate(obj):
            errs.extend(check_schema(v, schema["items"], f"{path}[{i}]", root))
    return errs


# ---------------------------------------------------------------------------
# Derived booleans, in one place
# ---------------------------------------------------------------------------

_PROB_LANGUAGE_RE = re.compile(r"(\d|%|percent|one in|out of|to one|in ten|in a hundred|fifty[- ]fifty|coin flip)", re.I)


def probability_language_ok(language: str | None) -> bool:
    """A stated number, percent or odds phrase must be in the words the speaker used."""
    return bool(language) and bool(_PROB_LANGUAGE_RE.search(language))


def extraction_qualifies(gates: dict, resolution_criteria: str | None) -> bool:
    return all(bool(gates.get(g)) for g in GATES) and bool((resolution_criteria or "").strip())


def verification_qualifies(v: dict) -> bool | None:
    if v.get("status") != "ok":
        return None
    gates = v.get("gates") or {}
    return all(bool(gates.get(g)) for g in GATES) and v.get("attribution") == "subject" and bool(v.get("claim_faithful"))


# ---------------------------------------------------------------------------
# Date holds (release 2.3)
# ---------------------------------------------------------------------------
#
# The models noticed wrong dates many times and wrote it in notes nothing reads
# (rescue round 4, design summary). From 2.3 a doubt is a field, and three
# mechanical checks join it. Each one HOLDS the record: it stays on file with
# both verdicts and is not accepted until the recording is dated and the
# transcript extracted again. A hold is DERIVED from the record's own fields, so
# the validator recomputes it rather than trusting the stored list.

# Words that stand in for a year the writer did not resolve. A1 wrote "the second
# half of the statement year" against a record it could not date. With a known
# statement date the year can be written, so a placeholder in a field that names
# NO year means the date was not trusted or not read (design 2.5 (a)). A field
# that names its year as well is only wordy: MEASURED 2026-09-30 on the accepted
# corpus, 7 of 9 placeholder hits sat beside the year itself ("within the year
# following the recording, no later than 2020-07-16"), and holding those would
# drop records that resolve exactly as written.
PLACEHOLDER_YEAR_RE = re.compile(
    r"\b(?:statement\s+year|the\s+(?:calendar\s+)?year\s+(?:following|after|of)\s+the\s+(?:recording|statement))\b",
    re.I)
_YEAR_WORD_RE = re.compile(r"\b(?:19|20)\d\d\b")
HOLD_TEXT_FIELDS = (("prediction", "normalized_claim"), ("prediction", "resolution_criteria"),
                    ("verification", "verifier_resolution_criteria"))


def merge_doubts(doubts: list[dict]) -> dict:
    """One transcript-level doubt from several batch answers: the holding doubt wins, then cannot_tell."""
    if not doubts:
        raise PredictionError("statement_date_doubt: no answer to merge")
    for want in (HOLDING_DOUBT, "cannot_tell"):
        hit = next((d for d in doubts if d.get("doubt") == want), None)
        if hit is not None:
            return dict(hit)
    return dict(doubts[0])


def relative_year_problem(rec: dict) -> dict | None:
    """A relative year the extractor resolved differently from the funnel, or on a range that spans two years.

    Design 2.5 (b): when target_date_text is "this year", "next year" or a number of
    units, recompute the deadline from the statement date with the funnel's OWN
    parser and require the same year. This catches the CES 2006 keynote, where the
    extractor resolved "this year" from context against a 2013 upload. A year in
    the speaker's own words is the extractor's to use, so those are not recomputed.

    Critique 1 point 13: "next year" from a date known only to lie between
    2024-12-20 and 2025-01-03 names two different years, so it is held, not guessed.
    """
    src, pred = rec.get("source") or {}, rec.get("prediction") or {}
    said, text, target = src.get("statement_date"), pred.get("target_date_text"), pred.get("target_date")
    if not (said and text and target) or _YEAR_WORD_RE.search(text):
        return None
    import phase2_resolvability as P2  # noqa: PLC0415 -- phase2_resolvability imports this module
    year_words = bool(P2.THIS_YEAR.search(text) or P2.NEXT_YEAR.search(text))
    if not (year_words or P2.NUMBER.search(text)):
        return None
    earliest = (src.get("statement_date_override") or {}).get("statement_date_earliest")
    if year_words and earliest and earliest[:4] != said[:4]:
        return {"check": "relative_year_on_ambiguous_range",
                "detail": f"{text!r} said between {earliest} and {said} names a different year for each end; "
                          f"target_date {target} cannot be checked"}
    probe = {**rec, "prediction": {**pred, "target_date": None, "horizon_years_inferred": None}}
    deadline, how = P2.derived_deadline(probe)
    if deadline is None:
        return None
    # EARLIER than the funnel's year means the words were resolved against some
    # other, older date: the CES 2006 case. LATER is usually right and is allowed:
    # the funnel's parser takes the first of two alternatives ("a year or two",
    # "10 years or 20 years") and knows no fiscal year ("this year" said in
    # October, resolved to a fiscal year ending 31 January). MEASURED 2026-09-30:
    # an exact-year rule held 15 accepted corpus records and 9 were those. More
    # than one year later for "this year" or "next year" has no such excuse.
    gap = int(target[:4]) - deadline.year
    if gap < 0 or (year_words and gap > 1):
        return {"check": "relative_year_mismatch",
                "detail": f"{text!r} said {said} gives {deadline.isoformat()} ({how}); target_date is {target}"}
    return None


def date_hold_reasons(rec: dict) -> list[dict]:
    """Why this record's date must be settled before it can be accepted. Empty when nothing holds it."""
    out: list[dict] = []
    for stage in ("extraction", "verification"):
        d = (rec.get(stage) or {}).get("statement_date_doubt")
        if isinstance(d, dict) and d.get("doubt") == HOLDING_DOUBT:
            out.append({"check": f"statement_date_doubt:{stage}", "detail": d.get("evidence") or "(no words quoted)"})
    said = (rec.get("source") or {}).get("statement_date")
    if said:
        for block, field in HOLD_TEXT_FIELDS:
            text = (rec.get(block) or {}).get(field) or ""
            m = None if _YEAR_WORD_RE.search(text) else PLACEHOLDER_YEAR_RE.search(text)
            if m:
                out.append({"check": f"placeholder_date:{field}",
                            "detail": f"{m.group(0)!r} written against the known statement date {said}"})
    rel = relative_year_problem(rec)
    if rel:
        out.append(rel)
    return out


def compute_accepted(rec: dict) -> bool:
    """Both verdicts qualify and, on a 2.3 record, nothing holds its date.

    A 2.2 record carries no date_hold, and its accepted flag is the published
    board, so it is judged by the rule it was written under. The hold is
    RECOMPUTED here, never read from the stored list, so a record edited to
    clear its hold is still refused.
    """
    ok = bool(rec["extraction"]["qualifies"]) and bool(rec["verification"].get("qualifies"))
    if "date_hold" in rec:
        ok = ok and not date_hold_reasons(rec)
    return ok


def empty_verification() -> dict:
    return {"status": "not_run", "harness": None, "requested_model": None, "served_model": None,
            "served_model_verified": None, "account": None, "router_account_id": None, "contract_id": None,
            "run_id": None, "verified_at_utc": None, "gates": None, "attribution": None, "claim_faithful": None,
            "qualifies_stated": None, "qualifies": None, "agreement": None,
            "verifier_resolution_criteria": None, "notes": None, "telemetry": None}


def normalise_provenance(harness: str, telemetry: dict, account: str | None, router_account_id: str | None) -> dict:
    """One shape across three arms whose telemetry keys differ.

    Fable reports the served model under judge_model and it is read from the CLI's
    modelUsage, so it is verified. Astra's served_model is an echo of the request
    (codex --json names no model), so it is NOT verified. Gemini reads the model
    from the init event, verified, and its account is the profile identity.
    """
    if harness == "fable":
        return {"harness": harness, "requested_model": telemetry.get("requested_model"),
                "served_model": telemetry.get("judge_model"), "served_model_verified": True,
                "account": account, "router_account_id": router_account_id}
    if harness == "astra":
        return {"harness": harness, "requested_model": telemetry.get("requested_model"),
                "served_model": telemetry.get("served_model"), "served_model_verified": False,
                "account": account or "codex", "router_account_id": router_account_id}
    if harness == "gemini":
        return {"harness": harness, "requested_model": telemetry.get("requested_model"),
                "served_model": telemetry.get("served_model"),
                "served_model_verified": bool(telemetry.get("served_model_verified")),
                "account": telemetry.get("profile_identity") or account, "router_account_id": router_account_id}
    raise PredictionError(f"provenance: unknown harness {harness!r}")


# ---------------------------------------------------------------------------
# Record assembly and serialisation
# ---------------------------------------------------------------------------

def make_record(rec: dict, roster_entry: dict | None, cand: dict, loc: dict, provenance: dict,
                contract_id: str, run_id: str, extracted_at_utc: str, telemetry: dict,
                statement_date_doubt: dict | None = None) -> dict:
    """Assemble one full record from a grounded extractor candidate. Pure.

    `statement_date_doubt` is the extractor's transcript-level answer (release
    2.3). With it the record carries the doubt, the claim form and a date_hold;
    without it the record has the 2.2 shape, as every existing caller built it.
    """
    text = rec["text"]
    start, end = loc["start"], loc["end"]
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    before, after = context_window(text, start, end)
    date, basis = derive_statement_date(rec)
    gates = {g: bool(cand["gates"].get(g)) for g in GATES}
    conf = dict(cand.get("confidence") or {})
    gate_notes = cand.get("gate_notes") or ""
    prob = conf.get("probability")
    ctype = conf.get("type") or "none"
    lang = conf.get("verbatim_confidence_language")
    if ctype == "explicit_probability" and not probability_language_ok(lang):
        # The model asserted a number the speaker's words do not carry. The number
        # is discarded and the candidate is disqualified with the reason on record.
        prob = None
        ctype = "qualitative" if lang else "none"
        gate_notes = (gate_notes + " | confidence_invented: probability dropped, no number in the language").strip(" |")
        gates["falsifiable"] = gates["falsifiable"] and False
    if ctype != "explicit_probability":
        prob = None
    if ctype == "none":
        lang = None
    criteria = cand.get("resolution_criteria") or ""
    out = {
        "schema_version": SCHEMA_VERSION,
        "prediction_id": prediction_id(tid, cand["quote"]),
        "transcript_id": tid,
        "leader_slug": rec["leader_slug"],
        "source_id": rec["source_id"],
        "speaker": {"slug": rec["leader_slug"],
                    "name": (roster_entry or {}).get("name") or rec["leader_slug"],
                    "role": (roster_entry or {}).get("role"),
                    "company": (roster_entry or {}).get("company")},
        "accepted": False,
        "status": "pending",
        "source": {
            "url": rec.get("url"), "video_id": rec.get("video_id"),
            "title": rec.get("yt_title") or rec.get("declared_title"),
            "venue": rec.get("declared_venue"), "kind": rec.get("declared_kind"),
            "statement_date": date, "statement_date_basis": basis,
            **({"statement_date_override": override_block(rec)} if basis == OVERRIDE_DATE_BASIS else {}),
            "quote": cand["quote"], "quote_original": text[start:end],
            "quote_char_start": start, "quote_char_end": end,
            "quote_word_count": quote_word_count(text[start:end]),
            "quote_occurrences": loc["occurrences"],
            "timestamp_mark": nearest_mark(text, start),
            "context_before": before, "context_after": after,
        },
        "prediction": {
            "normalized_claim": cand.get("normalized_claim") or "",
            "category": cand.get("category"), "prediction_type": cand.get("prediction_type"),
            "target_date": cand.get("target_date"), "target_date_text": cand.get("target_date_text"),
            "horizon": cand.get("horizon"),
            "horizon_years_inferred": cand.get("horizon_years_inferred") if cand.get("horizon") == "inferable" else None,
            "horizon_evidence": cand.get("horizon_evidence"),
            "resolution_criteria": criteria, "specificity": cand.get("specificity"),
            "subject_control": cand.get("subject_control"),
            **({"claim_form": cand["claim_form"]} if "claim_form" in cand else {}),
        },
        "confidence": {"type": ctype, "probability": prob, "verbatim_confidence_language": lang},
        "extraction": {
            "qualifies": extraction_qualifies(gates, criteria), "gates": gates, "gate_notes": gate_notes,
            **provenance, "contract_id": contract_id, "run_id": run_id,
            "extracted_at_utc": extracted_at_utc, "telemetry": telemetry,
        },
        "verification": empty_verification(),
        "resolution": dict(SENTINEL_RESOLUTION),
        "consensus": dict(SENTINEL_CONSENSUS),
    }
    if statement_date_doubt is not None:
        out["extraction"]["statement_date_doubt"] = dict(statement_date_doubt)
        out["date_hold"] = date_hold_reasons(out)
    return out


def serialise_line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def serialise_lines(records: list[dict]) -> str:
    ordered = sorted(records, key=record_sort_key)
    return "".join(serialise_line(r) + "\n" for r in ordered)


def jsonl_lines(text: str) -> list[str]:
    """Split a JSONL payload on "\\n" ONLY.

    `str.splitlines()` is wrong for JSONL and was the bug here. It also breaks
    on VT, FF, FS, GS, RS, NEL, U+2028 and U+2029, and JSON permits every one of
    those RAW inside a string. So a record containing one was cut in half, and
    the half parsed as `Unterminated string`, naming a column rather than the
    character responsible.

    MEASURED: a Stripe annual-letter PDF carried one U+2028 LINE SEPARATOR in an
    image caption. `json.loads` accepted the whole record happily; `parse_lines`
    never gave it the whole record. The file was 9564 bytes, 9522 characters,
    ONE "\\n" byte, and `splitlines()` returned two lines.

    The existing corpus never hit this because YouTube caption text carries none
    of these code points. Any source that has been through a PDF or a word
    processor can.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_lines(text: str, where: str = "") -> list[dict]:
    # Split on the newline BYTE, never str.splitlines(). splitlines() also breaks on
    # NEL, U+2028, U+2029, VT, FF and the four information separators, and json.loads
    # accepts every one of those RAW inside a string. A record carrying one is cut in
    # half and both halves then fail to parse.
    # FOUND by repo-1 on 2026-09-14 in a Stripe PDF caption carrying U+2028. The
    # YouTube corpus has none of these characters, so this is invisible today and
    # fires the moment a web-sourced record lands: VERIFIED against repo-1's
    # supplemental run, where exactly one of 72 files splits into 2 pieces that both
    # fail to parse.
    out = []
    # jsonl_lines() drops the trailing empty produced by the newline every
    # serialised file ends with. Same semantics as the inline form this replaces,
    # and it splits ONCE: the inline version recomputed len(text.split("\n"))
    # on every iteration, which is quadratic in the number of records.
    for n, line in enumerate(jsonl_lines(text), 1):
        if not line.strip():
            raise PredictionError(f"{where}:{n}: blank line inside a predictions file")
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PredictionError(f"{where}:{n}: {exc}") from exc
    return out


def utc_now() -> str:
    return utcnow()


__all__ = [n for n in dir() if not n.startswith("_")]
