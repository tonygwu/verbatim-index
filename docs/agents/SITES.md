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

## Where things are

- Published site: `site/index.html`, deployed with the guarded `scripts/deploy.sh` to
  `verbatim-index.tonygwu.com`
