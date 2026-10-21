# Published pages

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you change `build_site.py`,
`build_predictions_site.py` or anything that sets the size or shape of a
published page.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Rules that exist because something broke

- **The published page is held under a link crawler's fetch limit, and the
  evidence lives beside it.** FOUND 2026-09-17, by trying to post the board to
  Twitter: the card validator answered `ERROR: Fetching the page failed because
  the response is too large`, and the link posted bare. Every og: and twitter:
  tag was correct and in the head. The crawler never read them, because
  `build_site.py` inlined the whole audit as `const AUDIT = {...}` and the
  document was 16,044,532 bytes. Each leader's grades now go to
  `site/audit/<slug>.json`, fetched when that row is opened, and the page is
  418,420 bytes. A missing file comes back as the page itself with status 200,
  because the asset worker serves single-page-application fallbacks, so the
  drawer checks that it parsed JSON and says what it got instead of showing an
  empty drawer that would read as "no evidence exists". `MAX_PAGE_BYTES` is
  2,000,000 and a render over it REFUSES: that number is not Twitter's, which
  is unpublished, it is a line far below anything plausible so a breach is
  caught at render rather than by a link that quietly unfurls bare. Guarded by
  `scripts/test_site_evidence_split.py`, 26 checks, verified failing against
  the pre-fix renderer. `site/index.html` is a build artifact and so is
  `site/audit/`; both are ignored here, because the evidence is data.
  The predictions page had the same shape and was fixed the same day, the same
  way: 4,716,433 bytes of which `const PRED` was 4,536,549, now 182,813 with
  each person's records in `site-predictions/predictions/<slug>.json`. Whether
  it was ever over the limit is UNMEASURED, and stays that way. Nobody put it
  through the validator before the split, and Twitter does not publish the
  number, so do not read the fix as evidence that it was broken.
  In both scripts the files are written AFTER the page passes its size check,
  never before. A refused render must leave the site's data as the last good
  render left it: files newer than the page that points at them is the stale
  pair this repo keeps finding in other forms.
- **The predictions page has a phone layout at 940 px wide and narrower, and
  every row must show its name, Came true and Score without sideways scrolling.**
  FOUND 2026-10-21, before the page was announced on Twitter: on an iPhone 12
  (390 px) the board was its 1100 px desktop table inside a 340 px card that
  scrolled sideways with nothing saying so. Its columns ended at x = 423
  (Person), 569 (Organisation), 923 (When it was said), 1018 (Came true) and
  1125 (Score), so a reader saw names and half of each organisation, never a
  result. A person's predictions opened inside that row and were cut at the
  screen edge, and the fixed THEME button sat over the board's header. The fix
  is one `@media (max-width:940px)` block in `build_predictions_site.py`. It
  holds every phone rule, so desktop widths never match it, and it changes no
  markup or script. At 1280x800 and 1440x900 the top of the page, the board and
  Michael Dell's opened view were pixel-identical before and after. On a phone:
  each row is a three-column grid, with the person first, the role and
  organisation under the name, then Came true and Score. The Predictions
  breakdown, the When-it-was-said squares, the year axis, the paragraph under
  the board that explains the squares (`.sqlegend`), and the Organisation,
  Predictions and When headers are hidden, so only Person, Came true and Score
  sort there. The person view wraps every line (`overflow-wrap:anywhere`),
  stacks each label over its value and puts the filters in one column. The
  THEME button is `position:absolute`, so it scrolls away with the masthead.
  940 px covers phones held either way up, and tablets held upright (an iPad is
  768 to 834 px), which lose the breakdown and the squares too. Between 941 and
  about 1150 px the full table still scrolls sideways inside its card, as it
  always has. The Came true and Score columns are 70 px and 74 px wide on a
  phone: room for "27/27", the widest value on 2026-10-21, but a three-digit
  count such as "100/120" would run into Score.
  `scripts/test_predictions_phone_layout.py` measures the fixture page at 390 px
  and 360 px in headless Chrome. Board rows, Came true, Score and the opened
  view must stay inside the viewport, no text may leave its own cell, both sort
  headers must be on screen and uncovered, the THEME button may cover no text,
  and the squares' explanation shows only where the squares do. Headless Chrome will not open a window narrower than 500 px, so the page
  is measured in an iframe of the exact width, and the test checks that width
  first. No Chrome is a FAIL. `--site <dir> --person <slug>` runs the same
  checks on a real render. Hiding a column on phones hides its words there, so
  compare a change's visible text at desktop width, where it must not move.

## Where things are

- Published site: `site/index.html`, deployed with the guarded `scripts/deploy.sh` to
  `verbatim-index.tonygwu.com`
- Social cards: `site/og.png` and `site-predictions/og.png`, drawn by
  `scripts/build_og_card.py` and committed with an `og.meta.json` that records
  every figure drawn. Both draw the top three rows of their board and a strip of
  totals. Since 2026-10-20 the predictions card takes every figure from
  `card_figures()` in `build_predictions_site.py`, the function the page build
  compares the sidecar with. So a ranking, Score, Came true or total that moves
  after the card was drawn prints a warning on the next render; redraw with
  `build_og_card.py --site predictions --index ... --scores ... --roster ...`.
  `scripts/test_predictions_og_card.py` guards it.
  The predictions page's `og:image:alt` and `twitter:image:alt` describe that
  card in two sentences. Since 2026-10-21, `og_alt()` writes them from the figures
  `og.meta.json` records the card was drawn with, never from typed numbers: the
  people ranked, the predictions scored and extracted, the as-of date, and each
  top row's name, organisation, Score and Came true. A text over the 420
  characters `twitter:image:alt` allows refuses the render. A card with no
  ranking on record keeps the old "Verbatim Predictions." and title text.
