// Behavioural test for the (?) column tooltips on the rendered leaderboard.
//
// The one that matters is T5. The (?) sits inside a sortable <th>, and the
// table's click handler is delegated on document via closest("thead th"), so
// without an explicit guard a click on the (?) also sorts the column. Removing
// the guard makes T5 fail, which is how this test was checked.
//
// Needs jsdom, which is not a dependency of this repo:
//   npm install jsdom && node scripts/test_site_tooltip.js site/index.html
const fs = require("fs");
let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch { console.log("SKIP: jsdom not installed (npm install jsdom)"); process.exit(0); }

const file = process.argv[2] || "site/index.html";
const dom = new JSDOM(fs.readFileSync(file, "utf8"), {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(w) {
    w.matchMedia = () => ({ matches: false, addListener(){}, removeListener(){},
                            addEventListener(){}, removeEventListener(){} });
    w.scrollTo = () => {};
  },
});
const { window } = dom;
const doc = window.document;
const results = [];
const check = (name, cond, detail="") =>
  results.push({ name, pass: !!cond, detail });

const click = el => el.dispatchEvent(new window.MouseEvent("click",
  { bubbles: true, cancelable: true, view: window }));

// --- T1: the (?) exists on the Halo header ------------------------------
const btn = doc.querySelector('thead th[data-k="halo"] button.info');
check("T1 (?) button present on Halo header", btn);
if (!btn) { report(); process.exit(1); }

const sortState = () =>
  [...doc.querySelectorAll("thead th")].map(t => t.getAttribute("aria-sort") || "").join("|");

// --- T2: clicking (?) shows the tooltip with Halo copy -------------------
const before = sortState();
click(btn);
const tip = doc.getElementById("tip");
check("T2 tooltip visible after click", tip && !tip.hidden);
check("T3 tooltip explains blinded-vs-shown grading",
      tip && /graded twice/i.test(tip.innerHTML) && /blinded/i.test(tip.innerHTML));
check("T4 tooltip states sign meaning",
      tip && /pushed the score up/i.test(tip.innerHTML) && /pushed the score down/i.test(tip.innerHTML));

// --- T5: THE GUARD. clicking (?) must NOT sort the table -----------------
check("T5 clicking (?) does not sort the table", sortState() === before,
      `sort state before=[${before}] after=[${sortState()}]`);

// --- T6: sorting still works when the header text is clicked -------------
const th = doc.querySelector('thead th[data-k="halo"]');
click(th);
check("T6 clicking the header still sorts", th.getAttribute("aria-sort"),
      `aria-sort=${th.getAttribute("aria-sort")}`);

// --- T7: Escape closes it ------------------------------------------------
click(btn);
doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
check("T7 Escape hides the tooltip", tip.hidden);

// --- T8: accessible ------------------------------------------------------
check("T8 (?) has an accessible label", btn.getAttribute("aria-label"),
      btn.getAttribute("aria-label") || "(none)");

function report(){
  const w = Math.max(...results.map(r => r.name.length));
  for (const r of results)
    console.log(`  ${r.pass ? "PASS" : "FAIL"}  ${r.name.padEnd(w)}  ${r.detail}`);
  const failed = results.filter(r => !r.pass).length;
  console.log(`  ${results.length - failed}/${results.length} passed`);
  return failed;
}
process.exit(report() ? 1 : 0);
