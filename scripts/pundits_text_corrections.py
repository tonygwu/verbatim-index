"""Human caption corrections over immutable raw token offsets.

The original transcript and grades stay intact. A replacement is selected as one
phrase, so a change in word count cannot shift existing speaker annotations.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from atomicio import write_atomic
from pundits_speaker_spans import sidecar_path, text_hash, token_kinds


def validate_corrections(value: dict, transcript: dict) -> None:
    for key in ("key", "text_sha256", "token_count"):
        if value.get(key) != transcript[key]:
            raise ValueError("transcript changed; reload before correcting text")
    if not isinstance(value.get("edits"), list) or not value.get("checked_by"):
        raise ValueError("corrections require edits and checked_by")
    kinds = token_kinds(transcript["tokens"])
    end = 0
    for edit in value["edits"]:
        if not isinstance(edit, dict):
            raise ValueError("each correction must be an object")
        a, b = edit.get("start"), edit.get("end")
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(kinds) or a < end:
            raise ValueError("corrections must be ordered, non-overlapping ranges")
        if any(k != "speech" for k in kinds[a:b]):
            raise ValueError("select spoken words within one caption segment, without gaps or timestamps")
        if edit.get("original") != " ".join(transcript["tokens"][a:b]):
            raise ValueError("original words do not match the transcript")
        replacement = edit.get("replacement")
        if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > 4000:
            raise ValueError("replacement must contain 1–4000 characters; use Restore original to undo")
        if replacement == edit["original"]:
            raise ValueError("replacement is unchanged; use Restore original to undo")
        end = b


def update_corrections(value: dict, previous: dict | None, transcript: dict) -> dict:
    validate_corrections(value, transcript)
    previous = previous or {}
    if previous:
        validate_corrections(previous, transcript)
    revision = previous.get("revision", 0)
    if type(value.get("revision")) is not int or value["revision"] != revision:
        raise ValueError("Corrections changed in another window. Reload before saving.")
    now = datetime.now(timezone.utc).isoformat()
    # History is appended by the server, never trusted from the browser.
    edits = [{k: e[k] for k in ("start", "end", "original", "replacement")} for e in value["edits"]]
    event = {"revision": revision + 1, "updated_at": now, "checked_by": value["checked_by"],
             "before": previous.get("edits", []), "after": edits}
    return {"schema_version": 1, "key": transcript["key"], "text_sha256": transcript["text_sha256"],
            "token_count": transcript["token_count"], "revision": revision + 1, "edits": edits,
            "checked_by": value["checked_by"], "updated_at": now,
            "history": [*previous.get("history", []), event]}


def corrected_text(transcript: dict, value: dict) -> str:
    validate_corrections(value, transcript)
    tokens, pieces, at = transcript["tokens"], [], 0
    for edit in value["edits"]:
        pieces.extend(tokens[at:edit["start"]]); pieces.append(edit["replacement"])
        at = edit["end"]
    pieces.extend(tokens[at:])
    return " ".join(pieces)


def export_corrections(answers: Path, page: Path, out: Path) -> dict:
    """Export corrected reading text; does not overwrite source or grading inputs."""
    raw = json.loads(answers.read_text())
    recordings = {}
    for key, value in raw.get("corrections", {}).items():
        transcript = json.loads(sidecar_path(page, key).read_text())
        text = corrected_text(transcript, value)
        recordings[key] = {**value, "corrected_text": text, "corrected_text_sha256": text_hash(text)}
    result = {"schema_version": 1, "recordings": recordings,
              "note": "Human caption corrections; whitespace normalized. Offsets still refer to original tokens. "
                      "Existing scores use the original captions; regrading is a separate step."}
    write_atomic(out, json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for flag in ("--answers", "--page", "--out"):
        ap.add_argument(flag, type=Path, required=True)
    args = ap.parse_args()
    result = export_corrections(args.answers, args.page, args.out)
    print(f"Exported corrections for {len(result['recordings'])} recordings")
