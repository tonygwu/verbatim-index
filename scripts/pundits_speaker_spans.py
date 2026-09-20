"""Sparse speaker annotations, keyed to immutable raw-transcript word offsets.

Model evidence is a suggestion, never a human label. Uncovered words are unknown;
neither speaker share nor the presence of a name can supply their attribution.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from atomicio import write_atomic

SPEAKERS = {"subject", "other", "unclear"}
ORIGINS = {"human", "model_confirmed"}


def token_kinds(tokens: list[str]) -> list[str]:
    """Caption metadata is never speech, without changing existing raw offsets."""
    kinds = []
    for i, word in enumerate(tokens):
        if re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\]", word):
            kind = "timestamp"
        elif re.fullmatch(r">{2,}", word):
            kind = "turn"
        elif re.fullmatch(r"[\[\]_…]+|\.{2,}|\[(?:inaudible|music|applause|laughter)\]", word, re.I):
            kind = "gap"
        elif not re.search(r"\w", word):
            kind = "punctuation"
        else:
            kind = "speech"
        kinds.append(kind)
    return kinds


def quote_review(quote: dict, transcript: dict, annotation: dict) -> dict:
    """Unreviewed speech is pending; explicit uncertainty is a completed review."""
    validate_annotation(annotation, transcript)
    kinds = token_kinds(transcript["tokens"])
    start, end = quote["quote_start"], quote["quote_end"]
    if not 0 <= start < end <= len(kinds):
        raise ValueError("quote offsets are outside the transcript")
    speech = [i for i in range(start, end) if kinds[i] == "speech"]
    labels = {i: r["speaker"] for r in annotation["ranges"]
              for i in range(max(start, r["start"]), min(end, r["end"])) if kinds[i] == "speech"}
    missing = [i for i in speech if i not in labels]
    uncertain = sum(v == "unclear" for v in labels.values())
    answer = None
    if speech and not missing:
        answer = "unclear" if uncertain else "both" if len(set(labels.values())) > 1 else next(iter(labels.values()))
    return {"answer": answer, "review_status": "complete" if answer else "incomplete",
            "total_words": len(speech), "reviewed_words": len(labels),
            "unreviewed_words": len(missing), "unclear_words": uncertain,
            "first_unreviewed": missing[0] if missing else None}


def reconcile_quote_reviews(answers: dict, page: Path, quote_rows: list[dict]) -> dict:
    """Project saved ranges onto quotes, leaving source ranges/legacy answers intact.

    Used by GET, atomic saves and import. Reading an old file never rewrites it.
    A stale annotation cannot supply a completed quote decision.
    """
    out = {**answers, "attribution": dict(answers.get("attribution", {}))}
    for row in quote_rows:
        annotation = answers.get("spans", {}).get(row["key"])
        if annotation is None:
            continue
        for quote in row.get("quotes", []):
            if "quote_start" not in quote:
                continue
            previous = out["attribution"].get(quote["qid"], {})
            try:
                transcript = json.loads(sidecar_path(page, row["key"]).read_text())
                result = quote_review(quote, transcript, annotation)
            except (OSError, ValueError) as exc:
                result = {"answer": None, "review_status": "stale", "review_error": str(exc)}
            legacy = previous.get("legacy_answer")
            if legacy is None and previous.get("review_method") != "range_review_v2":
                legacy = previous.get("answer")
            out["attribution"][quote["qid"]] = {**previous, **result, "qid": quote["qid"], "key": row["key"],
                "review_method": "range_review_v2", "legacy_answer": legacy,
                "checked_by": annotation["checked_by"], "updated_at": annotation.get("updated_at")}
    return out


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sidecar_path(page: Path, key: str) -> Path:
    parts = key.split("/")
    if len(parts) != 2 or any(not re.fullmatch(r"[\w-]+", p) for p in parts):
        raise ValueError("invalid recording key")
    return page.with_suffix(".transcripts") / parts[0] / (parts[1] + ".json")


def build_transcript(key: str, raw: str, grades: list[tuple[Path, dict]]) -> dict:
    from pundits_verify_page import locate, MARK

    matches = list(re.finditer(r"\S+", raw))
    tokens = [m.group() for m in matches]
    suggestions = []
    seen = set()
    skipped = 0
    for path, record in grades:
        if record.get("validation_errors") or (record.get("run") or 0) != 0:
            continue
        for dim, body in (record.get("grade", {}).get("dimensions") or {}).items():
            for evidence in body.get("evidence") or []:
                speaker = evidence.get("speaker")
                if speaker not in {"subject", "interlocutor", "clip"}:
                    continue
                quote = evidence.get("quote") or ""
                span = locate(quote, raw)
                if span is None:
                    skipped += 1
                    continue
                start, last = span
                # A repeated phrase is not a trustworthy position. Do not guess.
                if locate(quote, raw[matches[start].end():]) is not None:
                    skipped += 1
                    continue
                label = "subject" if speaker == "subject" else "other"
                ident = (start, last + 1, label, record.get("judge"), record.get("mode"), dim)
                if ident in seen:
                    continue
                seen.add(ident)
                suggestions.append({"start": start, "end": last + 1, "speaker": label,
                                    "judge": record.get("judge"), "mode": record.get("mode"),
                                    "dimension": dim, "original_speaker": speaker,
                                    "grade_file": path.name, "grade_sha256": text_hash(path.read_text()),
                                    "matched_piece": "..." in quote or "…" in quote})
    times = []
    for i, token in enumerate(tokens):
        mark = MARK.fullmatch(token)
        if mark:
            h, m, s = map(int, mark.groups())
            times.append([i, h * 3600 + m * 60 + s])
    return {"schema_version": 1, "key": key, "text_sha256": text_hash(raw),
            "suggestions_sha256": text_hash(json.dumps(suggestions, sort_keys=True)),
            "token_count": len(tokens), "tokens": tokens, "times": times,
            "suggestions": suggestions, "unlocated_or_ambiguous": skipped,
            "suggestion_scope": "Located evidence quotes only; all other words unknown."}


def validate_annotation(value: dict, transcript: dict) -> None:
    if value.get("key") != transcript["key"]:
        raise ValueError("recording key does not match")
    if value.get("text_sha256") != transcript["text_sha256"] or value.get("token_count") != transcript["token_count"]:
        raise ValueError("transcript changed; reload before annotating")
    ranges = value.get("ranges")
    if not isinstance(ranges, list):
        raise ValueError("ranges must be a list")
    end = 0
    for span in ranges:
        if not isinstance(span, dict):
            raise ValueError("each range must be an object")
        a, b = span.get("start"), span.get("end")
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= transcript["token_count"] or a < end:
            raise ValueError("ranges must be ordered, non-overlapping word offsets within the transcript")
        if span.get("speaker") not in SPEAKERS or span.get("origin") not in ORIGINS:
            raise ValueError("a range needs a speaker and explicit human confirmation")
        end = b
    if not value.get("checked_by"):
        raise ValueError("checked_by is required")


def import_spans(export: Path, page: Path, out: Path) -> dict:
    answers = json.loads(export.read_text())
    result = {}
    # Validate the entire batch before writing any output.
    for key, value in answers.get("spans", {}).items():
        transcript = json.loads(sidecar_path(page, key).read_text())
        validate_annotation(value, transcript)
        kinds = token_kinds(transcript["tokens"])
        ranges = [{**s, "text": " ".join(transcript["tokens"][s["start"]:s["end"]]),
                   "speech_text": " ".join(transcript["tokens"][i] for i in range(s["start"], s["end"])
                                            if kinds[i] == "speech")}
                  for s in value["ranges"]]
        result[key] = {**value, "ranges": ranges}
    payload = {"schema_version": 1, "recordings": result,
               "note": "Sparse, assisted human annotations. Unmarked words remain unknown. "
                       "These do not rewrite grades or constitute a blind attribution audit."}
    write_atomic(out, json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return payload
