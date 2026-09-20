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
The quote answer is derived automatically from reviewed speech words only.

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

## Follow-up: one decision, readable captions

The operator found the two-stage workflow confusing: range labels plus a second
row of quote buttons. Removed the second decision and its old shortcuts. The
server now derives each quote's result in the same atomic write as its ranges.
The UI shows one non-editable result with the number of actual quote words left
to review and a button to select the next unfinished span. Surrounding words
remain optional and do not change that quote's result. Clearing words reopens
review. Only explicit Unsure markings yield an uncertain completed review.

Caption timestamps are omitted from passage text and become separate playback
cues in full view. Placeholder tokens and standalone ellipses become nonselectable
caption-gap badges. Speaker-turn tokens become neutral separators. All are
excluded from selection counts, range text previews, and quote coverage; raw
indices and existing stored ranges stay stable. The range list starts collapsed,
selection shading is continuous instead of boxing every word, and copy is shorter.

The actual saved example contained three ranges around a 20-word quote, with none
of those 20 words marked. The former apply button stored that as unclear. Its
source ranges are preserved; the UI and importer now correctly report incomplete.
Legacy answer files are projected at read time without being rewritten. Future
saves retain the prior coarse answer as legacy_answer for provenance.

Follow-up validation: span regressions 9/9, page/import 31/31, server 24/24.
The isolated browser check passed real dragging, automatic atomic quote results,
clearing back to pending, explicit uncertainty, caption-gap selection, reload and
mobile layout. A read-only live check confirmed the saved labels and all three
ranges are unchanged, the 20-word quote is pending, full view loads, and no
JavaScript errors or 390px overflow occur. The answer file remained byte-identical.
The full suite still has only the same three leaders-data failures listed above.
The updated local server is intentionally left running on port 5001 for labelling;
its process ID is recorded in /tmp/pundits-speaker-check-server.pid.

## Caption corrections

Select the misheard words in the same passage and choose Correct text. A compact
inline editor shows the original and asks what was actually said. Save displays
the replacement; a collapsed correction list exposes Edit and Restore original.
Corrections retain raw token anchors and an append-only server history. A phrase
with a changed word count is one selectable unit; it cannot shift later speaker
ranges. The original judge quote stays visible, with a note when corrections
overlap it. Speaker review still addresses the original passage. Corrected reading
text can be exported for later ingestion; existing scores are not recalculated.
No new model calls or public deployment are part of this feature.

Validation: correction tests 4/4; the browser check passed editing with changed
word counts, save/reload/restore, intact original quote text, and speaker marking
after correction. The live operator-supplied correction was saved through the UI
and survived reload; prior recording labels, speaker ranges and quote decisions
were unchanged, as were source transcript bytes. Zero browser errors and no 390px
overflow. The full suite retains the same three unrelated failures listed above.
