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

# Failure taxonomy: grade.py's labels plus the two this pipeline can add.
E_ROUTER = "router_no_account"
E_VERIFIER_SAME = "verifier_same_harness"
E_UNGROUNDED = "quote_not_grounded"
ALL_ERROR_TYPES = tuple(_GRADE_ERROR_TYPES) + (E_ROUTER, E_VERIFIER_SAME, E_UNGROUNDED)


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


def dedupe_overlapping(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse candidates whose character ranges overlap within one transcript.

    Each candidate carries start, end and prediction_id. Keep the longer span;
    tie on the smaller start; tie on the smaller id. One pass over candidates
    sorted by (start, -length, id): a candidate is dropped when it overlaps any
    kept one. Dropped entries are returned with `kept_by`, never discarded silently.
    """
    order = sorted(cands, key=lambda c: (c["start"], -(c["end"] - c["start"]), c["prediction_id"]))
    kept: list[dict] = []
    dropped: list[dict] = []
    for c in order:
        clash = next((k for k in kept if c["start"] < k["end"] and k["start"] < c["end"]), None)
        if clash is None:
            kept.append(c)
        else:
            if (c["end"] - c["start"], -c["start"], c["prediction_id"]) > \
               (clash["end"] - clash["start"], -clash["start"], clash["prediction_id"]) and \
               (c["end"] - c["start"]) > (clash["end"] - clash["start"]):
                # A later-starting but LONGER span beats the kept one.
                kept.remove(clash)
                dropped.append({"prediction_id": clash["prediction_id"], "start": clash["start"],
                                "end": clash["end"], "kept_by": c["prediction_id"]})
                kept.append(c)
            else:
                dropped.append({"prediction_id": c["prediction_id"], "start": c["start"],
                                "end": c["end"], "kept_by": clash["prediction_id"]})
    kept.sort(key=lambda c: (c["start"], c["prediction_id"]))
    return kept, dropped


# ---------------------------------------------------------------------------
# Dates and the market cutoff
# ---------------------------------------------------------------------------

def derive_statement_date(rec: dict) -> tuple[str | None, str]:
    """(YYYY-MM-DD, basis). yt_upload_date only; declared_year is never consulted.

    A malformed upload date raises: guessing a date would put a wrong 'said on'
    next to a quote and silently poison every horizon computed from it.
    """
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
    root = (root or data_root()).resolve()
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

def _contract(spec_path: Path, schema_path: Path) -> dict:
    """Same shape as grade.grading_contract: the pair of files a model sees, hashed together."""
    sb = spec_path.read_bytes()
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


def speaker_header(rec: dict, roster_entry: dict | None) -> str:
    """Never declared_year (a hardcoded constant), never today's date (invites resolution reasoning)."""
    name = (roster_entry or {}).get("name") or rec["leader_slug"].replace("-", " ").title()
    role = (roster_entry or {}).get("role") or "unknown"
    company = (roster_entry or {}).get("company") or "unknown"
    sector = (roster_entry or {}).get("sector") or "unknown"
    date, basis = derive_statement_date(rec)
    if date:
        date_line = f"Statement date: {date} (YouTube upload date; the recording is no later than this)"
    else:
        date_line = "Statement date: unknown"
    minutes = round((rec.get("duration_sec") or 0) / 60)
    return (
        f"Speaker: {name}\n"
        f"Role at the time: {role}\n"
        f"Company: {company}\n"
        f"Sector: {sector}\n"
        f"Title: {rec.get('yt_title') or rec.get('declared_title') or 'unknown'}\n"
        f"Venue: {rec.get('declared_venue') or 'unknown'}\n"
        f"Format: {rec.get('declared_kind') or 'unknown'}\n"
        f"{date_line}\n"
        f"Transcript length: {rec.get('word_count')} words\n"
        f"Duration: {minutes} minutes\n"
    )


def build_extraction_prompt(rec: dict, roster_entry: dict | None, spec: str, schema: str) -> str:
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    return f"""You extract forward-looking, falsifiable predictions that a named speaker made in one public
recording. Apply the specification below to the whole transcript and return one JSON object.

=========================== EXTRACTION SPEC ===========================
{spec}
======================== END EXTRACTION SPEC ==========================

TRANSCRIPT METADATA
{speaker_header(rec, roster_entry)}
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
            best = min(branches, key=len)
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


def compute_accepted(rec: dict) -> bool:
    return bool(rec["extraction"]["qualifies"]) and bool(rec["verification"].get("qualifies"))


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
                contract_id: str, run_id: str, extracted_at_utc: str, telemetry: dict) -> dict:
    """Assemble one full record from a grounded extractor candidate. Pure."""
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
    return {
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


def serialise_line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def serialise_lines(records: list[dict]) -> str:
    ordered = sorted(records, key=record_sort_key)
    return "".join(serialise_line(r) + "\n" for r in ordered)


def parse_lines(text: str, where: str = "") -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
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
