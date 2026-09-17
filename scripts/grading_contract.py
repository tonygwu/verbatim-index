#!/usr/bin/env python3
"""Grading contract v2: what a score depends on, and proof a stored grade still matches it.

WHY v2. The leaders study's contract (v1, `grade.grading_contract`) hashes
RUBRIC.md and the schema and nothing else. The prompt wrapper around them, the
sub-criteria list, the weights and the blinding all reach the judge or the score
without moving that hash, so a second study written on the same engine could
share a contract_id with the first and be pooled into it. v1 stays exactly as it
is for leaders, whose 2,260 grades depend on it. A study whose profile says
`contract_version: 2` uses this module instead.

TWO RECORDS, KEPT APART ON PURPOSE.
  CONTRACT    every setting that can change a score: the rubric, the schema, the
              prompt TEMPLATE with every conditional branch, the renderer
              version, the scoring definition, the identity treatment, the
              blinding rules and wordlist bytes, and each judge's request
              settings. Its hash is `contract_id`.
  PROVENANCE  where and from what a run happened: code commit, data revision,
              data path, site, discovery settings. Moving a checkout or renaming
              a domain changes provenance and leaves every grade valid. It is
              written once per run and referenced by id from each grade.

IDENTITY. Every v2 grade carries an `identity` block: study, contract, the hash
of the prompt actually sent, the hash of the exact input file, mode, judge,
requested model and run. A stored grade is reused only when every one of those
matches the job asking for it. A mismatch is reported naming the field and
never overwritten silently; `--force` moves the old record aside first.

AGGREGATION. `refuse_incompatible` rejects any grade whose study, contract or
roster slug does not match the current run, including a corpus that holds only
one contract when that contract is obsolete. There is no override.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTRACT_VERSION = 2
#: Bump when render_prompt's behaviour changes, even if no template changes.
RENDERER_VERSION = "template-v1"
SKILL_FILES = ("RUBRIC.md", "judge_output.schema.json", "PROMPT.md")
V2_PROFILE_KEYS = ("scoring", "identity_treatment", "blinding", "judge_requests")
IDENTITY_FIELDS = ("study_id", "contract_id", "prompt_sha256", "input_sha256",
                   "mode", "judge", "requested_model", "run")
MODES = ("blinded", "open")
PLACEHOLDERS = ("rubric", "schema", "transcript", "transcript_id", "metadata", "speaker_name",
                "subcriteria", "overall_formula", "max_quote_words")
EVIDENCE_SPEAKERS = ("subject", "interlocutor", "clip")
METADATA_LABELS = {
    "declared_kind": "Format as declared by the publisher",
    "declared_year": "Approximate year",
    "duration_minutes": "Duration in minutes",
    "word_count": "Transcript length in words",
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _repo_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO / p


def skill_dir(profile: dict) -> Path:
    return _repo_path(profile["skill_dir"])


def validate_scoring(scoring: dict) -> None:
    dims = scoring.get("dimensions")
    if not isinstance(dims, list) or not dims:
        raise RuntimeError("scoring.dimensions must be a non-empty list")
    keys, codes = [d.get("key") for d in dims], [c for d in dims for c in d.get("subcriteria", [])]
    if len(set(keys)) != len(keys) or len(set(codes)) != len(codes):
        raise RuntimeError(f"scoring has duplicate dimension keys or sub-criterion codes: {keys} {codes}")
    total = sum(float(d.get("weight", 0)) for d in dims)
    if abs(total - 1.0) > 1e-9:
        raise RuntimeError(f"scoring weights sum to {total}, not 1")
    for k in ("min_scored_subcriteria_per_dimension", "min_subject_quotes_per_dimension", "max_quote_words"):
        if not isinstance(scoring.get(k), int) or scoring[k] < 1:
            raise RuntimeError(f"scoring.{k} must be a positive integer")


def contract_v2(profile: dict) -> dict:
    """The contract for a v2 study. Raises, naming what is missing, rather than hashing less."""
    if profile.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeError(f"study {profile.get('study_id')!r} is not a contract v2 study")
    missing = [k for k in V2_PROFILE_KEYS if k not in profile]
    if missing:
        raise RuntimeError(f"profile {profile['study_id']!r} lacks contract fields {missing}")
    validate_scoring(profile["scoring"])
    sd = skill_dir(profile)
    files = {}
    for name in SKILL_FILES:
        f = sd / name
        if not f.is_file():
            raise RuntimeError(f"contract v2 needs {f}, which does not exist")
        files[name] = sha256_hex(f.read_bytes())
    blinding = dict(profile["blinding"])
    wordlist = blinding.pop("wordlist", None)
    blinding["wordlist_sha256"] = sha256_hex(_repo_path(wordlist).read_bytes()) if wordlist else None
    components = {
        "contract_version": CONTRACT_VERSION,
        "renderer_version": RENDERER_VERSION,
        "study_id": profile["study_id"],
        "files_sha256": files,
        "scoring": profile["scoring"],
        "identity_treatment": profile["identity_treatment"],
        "blinding": blinding,
        "judge_requests": profile["judge_requests"],
    }
    return {"contract_version": CONTRACT_VERSION, "study_id": profile["study_id"],
            "contract_id": sha256_hex(canonical(components).encode())[:16], "components": components}


# ---------------------------------------------------------------------------
# Prompt rendering. One template carries both modes, so the hash of the template
# covers every branch a judge can be sent.
#
#   <<<BLINDED>>> ... <<<END>>>     kept only in blinded mode
#   <<<OPEN>>> ... <<<END>>>        kept only in open mode
#   {{name}}                        one of PLACEHOLDERS; anything else is refused
#
# Placeholders are substituted in ONE pass over the template, so a transcript
# that happens to contain "{{rubric}}" is inserted as text, never expanded.
# ---------------------------------------------------------------------------

_BLOCK = re.compile(r"<<<(BLINDED|OPEN)>>>\n?(.*?)<<<END>>>\n?", re.S)
_PLACE = re.compile(r"\{\{([a-z_]+)\}\}")


def render_prompt(template: str, mode: str, values: dict[str, str]) -> str:
    if mode not in MODES:
        raise RuntimeError(f"unknown mode {mode!r}")
    body = _BLOCK.sub(lambda m: m.group(2) if m.group(1).lower() == mode else "", template)
    stray = re.findall(r"<<<[A-Z]+>>>", body)
    if stray:
        raise RuntimeError(f"template has unbalanced or unknown block markers: {sorted(set(stray))}")
    unknown = sorted({n for n in _PLACE.findall(body) if n not in PLACEHOLDERS})
    if unknown:
        raise RuntimeError(f"template uses unknown placeholders {unknown}; known: {list(PLACEHOLDERS)}")
    missing = sorted({n for n in _PLACE.findall(body) if n not in values})
    if missing:
        raise RuntimeError(f"no value supplied for placeholders {missing}")
    return _PLACE.sub(lambda m: str(values[m.group(1)]), body)


def metadata_block(rec: dict, fields: list[str]) -> str:
    """The same metadata lines in both modes. Year 0 is the fetcher's 'unknown'."""
    lines = []
    for f in fields:
        if f not in METADATA_LABELS:
            raise RuntimeError(f"identity_treatment names unknown metadata field {f!r}")
        if f == "duration_minutes":
            v = round((rec.get("duration_sec") or 0) / 60)
        elif f == "declared_year":
            v = rec.get("declared_year") or "unknown"
        else:
            v = rec.get(f)
        lines.append(f"{METADATA_LABELS[f]}: {v}")
    return "\n".join(lines)


def prompt_values(rec: dict, rubric: str, schema: str, profile: dict) -> dict[str, str]:
    scoring = profile["scoring"]
    return {
        "rubric": rubric,
        "schema": schema,
        "transcript": rec["text"],
        "transcript_id": f"{rec['leader_slug']}/{rec['source_id']}",
        "metadata": metadata_block(rec, profile["identity_treatment"]["metadata_fields"]),
        "speaker_name": rec.get("_speaker_name") or "",
        "subcriteria": " ".join(c for d in scoring["dimensions"] for c in d["subcriteria"]),
        "overall_formula": " + ".join(f"{d['weight']:.2f}*{d['key']}" for d in scoring["dimensions"]),
        "max_quote_words": str(scoring["max_quote_words"]),
    }


# ---------------------------------------------------------------------------
# Identity: what a stored grade must match before it may be reused.
# ---------------------------------------------------------------------------

def identity(**fields) -> dict:
    missing = [k for k in IDENTITY_FIELDS if fields.get(k) is None]
    extra = [k for k in fields if k not in IDENTITY_FIELDS]
    if missing or extra:
        raise RuntimeError(f"identity needs exactly {IDENTITY_FIELDS}; missing {missing}, extra {extra}")
    return {k: fields[k] for k in IDENTITY_FIELDS}


def identity_mismatch(record: dict, expected: dict) -> str | None:
    """None if the stored record carries exactly the expected identity, else EVERY difference.

    Every one, not the first: a changed mode also changes the prompt hash, and
    reporting only `prompt_sha256` would hide the cause from whoever reads it.
    """
    got = record.get("identity")
    if not isinstance(got, dict):
        return "identity: the stored record carries no identity block"
    diffs = [f"{k}: stored {got.get(k)!r}, job {expected[k]!r}"
             for k in IDENTITY_FIELDS if got.get(k) != expected[k]]
    return "; ".join(diffs) or None


def refuse_incompatible(grades: list[dict], contract: dict, roster_slugs: set[str]) -> dict:
    """Refuse a corpus holding any grade from another study, another contract or an unknown person."""
    problems: Counter = Counter()
    examples: dict[str, str] = {}
    for g in grades:
        tid = g.get("transcript_id") or f"{g.get('leader_slug')}/{g.get('source_id')}"
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        study = ident.get("study_id") or "leaders"
        cid = (g.get("grading_contract") or {}).get("contract_id")
        checks = (("study", study != contract["study_id"], f"{tid} is study {study!r}"),
                  ("contract", cid != contract["contract_id"], f"{tid} has contract {cid!r}"),
                  ("identity_contract", ident.get("contract_id") != contract["contract_id"],
                   f"{tid} identity names contract {ident.get('contract_id')!r}"),
                  ("roster", g.get("leader_slug") not in roster_slugs,
                   f"{tid} names {g.get('leader_slug')!r}, who is not on the roster"))
        for name, bad, why in checks:
            if bad:
                problems[name] += 1
                examples.setdefault(name, why)
    if problems:
        detail = "; ".join(f"{n} x{c} (e.g. {examples[n]})" for n, c in sorted(problems.items()))
        raise SystemExit(f"REFUSING TO AGGREGATE: {sum(problems.values())} incompatibilities with the "
                         f"current {contract['study_id']} contract {contract['contract_id']}: {detail}. "
                         f"Re-grade them under the current contract; they cannot be pooled.")
    return {"grades_checked": len(grades), "contract_id": contract["contract_id"]}


# ---------------------------------------------------------------------------
# Validation of a v2 grade against the profile's scoring definition.
# ---------------------------------------------------------------------------

def validate_v2(obj: dict, tid: str, scoring: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["grade is not a JSON object"]
    if obj.get("transcript_id") != tid:
        errs.append(f"transcript_id {obj.get('transcript_id')!r} != {tid!r}")
    dims = scoring["dimensions"]
    codes = [c for d in dims for c in d["subcriteria"]]
    subs = obj.get("subcriteria") if isinstance(obj.get("subcriteria"), list) else []
    got = [s.get("code") for s in subs if isinstance(s, dict)]
    if sorted(got) != sorted(codes) or len(got) != len(set(got)):
        errs.append(f"subcriteria codes {got} != exactly once each of {codes}")
    score_of = {s.get("code"): s.get("score") for s in subs if isinstance(s, dict)}
    for c, v in score_of.items():
        if not isinstance(v, int) or not 0 <= v <= 5:
            errs.append(f"sub-criterion {c} score {v!r} is not an integer 0-5")
    dobj = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    if sorted(dobj) != sorted(d["key"] for d in dims):
        errs.append(f"dimensions {sorted(dobj)} != {sorted(d['key'] for d in dims)}")
    all_supported = True
    for d in dims:
        x = dobj.get(d["key"])
        if not isinstance(x, dict):
            continue
        status = x.get("dimension_status")
        if status not in ("supported", "unsupported"):
            errs.append(f"{d['key']} dimension_status {status!r}")
            continue
        quotes = x.get("evidence") if isinstance(x.get("evidence"), list) else []
        for q in quotes:
            if not isinstance(q, dict) or q.get("speaker") not in EVIDENCE_SPEAKERS:
                errs.append(f"{d['key']} evidence speaker must be one of {EVIDENCE_SPEAKERS}")
        # An over-long quote is NOT an error here. It is recorded by
        # quote_overruns() and the grade is kept. See that function for why.
        scored = sum(1 for c in d["subcriteria"] if (score_of.get(c) or 0) > 0)
        subject_quotes = sum(1 for q in quotes if isinstance(q, dict) and q.get("speaker") == "subject")
        if status == "supported":
            if not isinstance(x.get("score"), int) or not 1 <= x["score"] <= 100:
                errs.append(f"{d['key']} is supported but score {x.get('score')!r} is not an integer 1-100")
            if scored < scoring["min_scored_subcriteria_per_dimension"]:
                errs.append(f"{d['key']} is supported on {scored} scored sub-criteria")
            if subject_quotes < scoring["min_subject_quotes_per_dimension"]:
                errs.append(f"{d['key']} is supported on {subject_quotes} subject quotes")
            if len(str(x.get("reasoning", "")).split()) < 20:
                errs.append(f"{d['key']} reasoning too short to audit")
        else:
            all_supported = False
            if x.get("score") is not None:
                errs.append(f"{d['key']} is unsupported but carries score {x.get('score')!r}")
    overall = obj.get("overall")
    if all_supported and not errs:
        want = sum(d["weight"] * dobj[d["key"]]["score"] for d in dims)
        if not isinstance(overall, (int, float)) or abs(overall - want) > 0.5:
            errs.append(f"overall {overall!r} != weighted {want:.2f}")
    elif not all_supported and overall is not None:
        errs.append("overall must be null when any dimension is unsupported")
    return errs


def quote_overruns(obj: dict, scoring: dict) -> list[dict]:
    """Every evidence quote longer than the cap, as a record rather than a rejection.

    The cap limits CITATION length. The judge reads the whole transcript; this
    only bounds how much of it may be pasted back as evidence. Rejecting the
    whole grade over one long quote threw away the score, the reasoning and both
    other dimensions, and bought the same answer again one word shorter.

    MEASURED 2026-09-16, which is why the penalty moved. Across eight P8a2
    rounds the cap rejected 24 grades, gemini 19 (19.0%) against fable 5 (5.0%),
    a ratio of 3.8x. In the P9 top-up all four rejections in the first 69 calls
    landed on `d3_good_faith`, for both judges and two different people. D3 asks
    whether a person applies one standard, answers the question asked, and
    concedes when warranted, and none of that is showable in one sentence. So
    the penalty was selecting D3 grades for quote brevity, on the dimension that
    carries 0.30 of the overall score.

    The cap number stays in the contract. Only the consequence moved, and the
    consequence is this code, which no hash covers, so `contract_id` is unchanged
    and grades collected under the old penalty stay poolable.

    Returns one entry per over-long quote, never a count, so aggregation can
    report what was cut and for which judge and dimension.
    """
    out: list[dict] = []
    cap = scoring["max_quote_words"]
    dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    for d in scoring["dimensions"]:
        x = dims.get(d["key"])
        if not isinstance(x, dict):
            continue
        quotes = x.get("evidence") if isinstance(x.get("evidence"), list) else []
        for q in quotes:
            if not isinstance(q, dict):
                continue
            words = len(str(q.get("quote", "")).split())
            if words > cap:
                out.append({"dimension": d["key"], "words": words, "cap": cap,
                            "speaker": q.get("speaker"),
                            "quote_head": " ".join(str(q.get("quote", "")).split()[:8])})
    return out


# ---------------------------------------------------------------------------
# Provenance: where a run happened. Never part of the contract.
# ---------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str | None:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def provenance(profile: dict, data_root: Path, argv: list[str]) -> dict:
    data_revision = _git(data_root, "rev-parse", "HEAD")
    if data_revision is None:
        raise RuntimeError(f"{data_root} is not a git checkout; a v2 run must name its data revision")
    body = {
        "study_id": profile["study_id"],
        "started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": _git(REPO, "rev-parse", "HEAD"),
        "code_worktree_dirty": bool(_git(REPO, "status", "--porcelain")),
        "data_root": str(Path(data_root).resolve()),
        "data_revision": data_revision,
        "data_worktree_dirty": bool(_git(data_root, "status", "--porcelain")),
        "publication_site": profile.get("publication_site"),
        "site_dir": profile.get("site_dir"),
        "discovery": profile.get("discovery"),
        "argv": list(argv),
    }
    return {"provenance_id": sha256_hex(canonical(body).encode())[:16], **body}


def write_provenance(out_root: Path, prov: dict) -> Path:
    dest = Path(out_root) / "_provenance" / f"{prov['provenance_id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prov, indent=1, sort_keys=True))
        tmp.replace(dest)
    return dest
