# Speaker-range editor

The operator requested multiple disjoint speech ranges and model-prefilled drafts
in the existing local speaker-check page. They chose displayed passages with an
option to expand to the full transcript (2026-09-20).

Keep the current typography, moderate density, light/dark tokens, responsive left
recording list and per-video flow. No new tabs or external hosting. Add a common
range editor in place of the ambiguous overlapping quote/name highlights.

Workflow: play the linked moment; drag across words; choose Subject, Someone else,
or Unclear. Repeat for discontinuous sections. Select/adjust an existing range
with start/end sliders, remove, or undo. Confirm model suggestions in the visible
passage explicitly. Full transcript expands in the same scrollable editor.
The quote itself has a separate exact-text block and an underline in the editor.
A separate action derives the quote answer from reviewed words only.

Model suggestions come only from located saved evidence, with judge, mode,
dimension and grade hash retained. Repeated/ambiguous matches are withheld;
conflicting suggestions remain unresolved. Uncovered words are unknown, never
inferred as Other. Existing coarse human quote answers take precedence initially.
Model drafts use a dashed border; human-reviewed spans use a solid border; colors
also have visible text labels. A human override is stored separately from grades.

Data: transcript sidecars contain raw whitespace tokens, original-text SHA-256,
word count, timestamp positions and model evidence. Human ranges use start/end
word offsets (end exclusive), speaker and confirmation origin. Backend rejects
changed hashes, bad offsets and overlapping ranges. Import retains raw text spans
and marks the annotations as assisted, unsuitable for a blind accuracy estimate.
Full texts remain only in the private data checkout and are served on loopback.

Verification: Python HTTP round-trip/validation/import tests and Playwright tests
exercise real selection, disjoint spans, shrinking, undo, full view, reload,
model confirmation, unclear words and quote-answer derivation. Existing recording
labels and quote answers must survive unchanged. No judge calls or board changes.

Measured validation on 2026-09-20: existing page/import tests 31/31, local server
24/24, new span tests 5/5. Browser checks passed for real mouse dragging, two
disjoint spans, shrinking/undo, explicit model confirmation, reloading saved
ranges, Subject/Both quote derivation, and a 390px layout without overflow. A
read-only check of the actual Steven Bonnell example loaded its 90-token passage
and expanded to all 9,456 tokens; light/dark screenshots were inspected without
changing human answers. No mobile touch-device interaction claim is made.

The full globbed suite had three unrelated leaders-data failures: the documented
roster count is 57 while the local roster has 50 (`test_agents_md_current_state`),
81 of 780 accepted predictions lack market provenance (`test_log_bloat`), and Amjad
Masad is both seated and on the exclusion list (`test_render_integrity`). These
inputs belong to leaders production and were not changed by this UI work.
