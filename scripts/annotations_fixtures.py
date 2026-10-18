"""Small annotation sessions for the tests. Synthetic only: nothing here reads a data checkout."""
from __future__ import annotations

from pathlib import Path

from annotations_page import page_payload
from annotations_store import SCHEMA_VERSION, Session, write_manifest


def write_session(root: Path, data: dict, *, modes=("speakers", "captions"), projects=("pundits",),
                  name: str = "t", page: str = "page.html") -> Session:
    """A session whose page is just the data block, with a valid version-2 manifest."""
    root.mkdir(parents=True, exist_ok=True)
    (root / page).write_text("<title>t</title><script>\nconst D = " + page_payload(data) + ";\n</script>\n")
    recordings = {k: {"projects": list(projects), "text_sha256": v.get("text_sha256", ""),
                      "token_count": v.get("token_count", 0)}
                  for k, v in data.get("transcript_index", {}).items()}
    write_manifest(root, {"schema_version": SCHEMA_VERSION, "tool": "annotations", "name": name,
                          "projects": list(projects), "modes": list(modes), "blind": True,
                          "transcript_dir": "transcripts",
                          "files": {"page": page, "answers": "human_answers.json", "quote_key": "quote_key.json"},
                          "recordings": recordings})
    return Session.open(root)
