"""The design tokens both Verbatim pages share: fonts and the :root colour block.

Moved out of build_site.py byte for byte on 2026-09-10 so the predictions page
uses the same palette without copying it. Tokens and fonts only. Component CSS
stays in each builder, because the two tables legitimately differ.
"""

FONT_LINKS = r"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">"""

THEME_CSS = r""":root{
  --ground:#F2F3F5; --surface:#FCFCFB; --surface-2:#E9EBEF;
  --ink:#15181D; --ink-2:#3C4450; --muted:#5B646F; --faint:#8A929C;
  --rule:#DCDFE5; --rule-strong:#C3C8D1;
  --d1:#2E6FC9; --d2:#BA5416; --d3:#00875A;
  /* Overall is deliberately achromatic. It is a summary of the other three,
     so giving it a fourth hue would read as a fourth dimension, and the old
     maroon was the Insight hue exactly. */
  --d0:#6B7280; --d0-soft:#9CA3AF;
  --d1-wash:#2E6FC91A; --d2-wash:#BA54161A; --d3-wash:#00875A1A;
  --warn:#9A6700; --bad:#A33A2A;
  --shadow:0 1px 2px #15181D0F, 0 4px 16px #15181D0A;
}
:root:not([data-theme="light"]){
  @media (prefers-color-scheme: dark){
    --ground:#121417; --surface:#1B1E23; --surface-2:#23272E;
    --ink:#E9ECF1; --ink-2:#C3C9D2; --muted:#9AA3AE; --faint:#6E7883;
    --rule:#2C3138; --rule-strong:#3B424B;
    --d1:#5A96DE; --d2:#D2702C; --d3:#2E9C6E;
    --d0:#9AA3B2; --d0-soft:#6F7787;
    --d1-wash:#5A96DE26; --d2-wash:#D2702C26; --d3-wash:#2E9C6E26;
    --warn:#D9A441; --bad:#E0806F;
    --shadow:0 1px 2px #00000040, 0 4px 16px #00000030;
  }
}
:root[data-theme="dark"]{
  --ground:#121417; --surface:#1B1E23; --surface-2:#23272E;
  --ink:#E9ECF1; --ink-2:#C3C9D2; --muted:#9AA3AE; --faint:#6E7883;
  --rule:#2C3138; --rule-strong:#3B424B;
  --d1:#5A96DE; --d2:#D2702C; --d3:#2E9C6E;
  --d0:#9AA3B2; --d0-soft:#6F7787;
  --d1-wash:#5A96DE26; --d2-wash:#D2702C26; --d3-wash:#2E9C6E26;
  --warn:#D9A441; --bad:#E0806F;
  --shadow:0 1px 2px #00000040, 0 4px 16px #00000030;
}"""
