#!/usr/bin/env python3
"""The speaker-check page's importer produces labels `report` accepts, and nothing it would not.

The page stores one db document per recording; `pundits_verify_page.py import`
turns an export of them into human_labels.json, which `pundits_pilot.py report`
reads to decide the P6 gate. A label the importer writes but `report` rejects
would silently drop a recording from the gate, and a partly answered recording
passed through would be a guessed label. So this checks the importer against
`report`'s own validator rather than restating its rules.

  VALID      every complete label passes pundits_pilot.human_errors unchanged
  EXCLUDED   a wrong-person or off-topic answer is kept, with all three fields
  PARTIAL    a recording missing any answer is left out and counted, never filled
  FOREIGN    a label for a recording not on the checklist stops the import
  PAGE       the built page carries each recording and no lean field
  TIMES      an excerpt's link time is the nearest earlier transcript mark
  LOCATE     a judge's quote is found in the raw transcript, [SUBJECT] and elisions included
  SIGNALS    a quote spanning a turn, a question in a conversation, and a self-naming
             quote are flagged; an ordinary answer is not
  HIDDEN     the judges' labels reach the private key file, never the page
  JOIN       quote answers join the key, and a foreign answer stops the import
  SHADOW     no function parameter hides a module-level binding its own body uses
  DRAFTS     with --drafts each recording carries its latest draft and needs_review's
             reasons; a draft for a recording off the checklist stops the build; without
             --drafts the rows are as before; draft_shown survives the import
  RENDER     run by node against a stub page: flagged recordings come first, each under
             its own section, the draft card and its tags show, and a saved answer
             carries draft_shown; a page without drafts has no sections

  .venv/bin/python scripts/test_pundits_verify_page.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


#: A stub page for node: enough DOM for the script to render, a local server that
#: answers with SAVED and records each save, and one "y" key press.
PAGE_HARNESS = r"""
const nodes = {};
const mk = id => nodes[id] ||= {id, innerHTML: "", textContent: "", className: "", hidden: false, style: {},
  setAttribute(k, v) { this[k] = v; }, querySelectorAll() { return []; }, querySelector() { return null; },
  addEventListener() {}, scrollIntoView() {}, closest() { return null; }, dataset: {}};
let keydown = null;
const posts = [];
global.document = {getElementById: mk, querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener(type, fn) { if (type === "keydown") keydown = fn; }, createElement: () => mk("x" + Math.random())};
global.window = {open() {}, addEventListener() {}, removeEventListener() {}};
global.location = {hash: ""};
global.history = {replaceState() {}};
global.CSS = {escape: s => s};
global.fetch = async (url, opt) => {
  if (url === "api/answers") return {ok: true, json: async () => SAVED};
  if (url === "api/answer") { posts.push(JSON.parse(opt.body)); return {ok: true, json: async () => ({ok: true})}; }
  throw new Error("unexpected fetch " + url);
};
let threw = "";
try { new Function(SCRIPT)(); } catch (e) { threw = String(e && e.stack || e).split("\n")[0]; }
setTimeout(() => {
  const list = nodes.list && nodes.list.innerHTML, detail = nodes.detail && nodes.detail.innerHTML;
  if (keydown) keydown({key: "y", target: {tagName: "BODY", closest: () => null}, preventDefault() {}});
  setTimeout(() => console.log(JSON.stringify({list, detail, posts, threw})), 20);
}, 20);
"""


def run_page(rows: list[dict], saved: dict | None = None) -> dict:
    """The page's own script run by node on `rows`, starting from the `saved` answers; what it rendered and saved."""
    import pundits_verify_page as V
    page = V.render_page(json.dumps({"rows": rows, "quote_rows": [], "venues": V.VENUES, "transcript_index": {}}))
    script = page[page.index("<script>") + len("<script>"):page.rindex("</script>")]
    # On stdin, not -e: a real page is about 1 MB, past the argument-length limit.
    head = f"const SCRIPT = {json.dumps(script)};\nconst SAVED = {json.dumps(saved or {'labels': {}, 'attribution': {}})};\n"
    n = subprocess.run(["node", "-"], input=head + PAGE_HARNESS,
                       capture_output=True, text=True, timeout=60)
    if n.returncode != 0 or not n.stdout.strip():
        return {"list": "", "detail": "", "posts": [], "threw": n.stderr[-400:]}
    out = json.loads(n.stdout.strip().splitlines()[-1])
    return {k: out.get(k) or ("" if k != "posts" else []) for k in ("list", "detail", "posts", "threw")}


def main() -> int:
    print("pundits speaker-check page")
    import pundits_pilot as P
    import pundits_verify_page as V

    checklist = {"p/a": {}, "p/b": {}, "p/c": {}, "p/d": {}}
    docs = [
        {"key": "p/a", "subject_present": True, "venue": "conversation", "political_content": True, "checked_by": "operator"},
        {"key": "p/b", "subject_present": False, "venue": "solo", "political_content": True, "checked_by": "operator", "notes": "guest only"},
        {"key": "p/c", "subject_present": True, "venue": "reaction", "political_content": False, "checked_by": "operator"},
        {"key": "p/d", "subject_present": True, "political_content": True},
    ]
    res = V.to_labels(docs, checklist)

    print("\n[VALID]")
    errs = {k: P.human_errors(v) for k, v in res["labels"].items()}
    check("every imported label passes report's own validator", all(not e for e in errs.values()), str(errs))

    print("\n[EXCLUDED]")
    check("a wrong-person answer is imported", res["labels"].get("p/b", {}).get("subject_present") is False)
    check("an off-topic answer is imported", res["labels"].get("p/c", {}).get("political_content") is False)
    check("notes survive the import", res["labels"].get("p/b", {}).get("notes") == "guest only")

    print("\n[PARTIAL]")
    check("a recording with no format is left out", "p/d" not in res["labels"])
    check("and counted as partial rather than dropped silently", res["partial"] == ["p/d"], str(res["partial"]))

    print("\n[FOREIGN]")
    try:
        V.to_labels(docs + [{"key": "q/zz", "subject_present": True, "venue": "solo", "political_content": True}], checklist)
        check("a label for a recording not on the checklist stops the import", False, "it was accepted")
    except SystemExit as exc:
        check("a label for a recording not on the checklist stops the import", "not on the checklist" in str(exc), str(exc))

    print("\n[TIMES]")
    ex = V.excerpts("[00:00:00] " + " ".join(f"w{i}" for i in range(400)) + " [00:05:07] " + " ".join(f"x{i}" for i in range(600)))
    check("three excerpts are cut", len(ex) == 3, str(len(ex)))
    check("a late excerpt links to the nearest earlier mark", ex[-1]["t"] == 307, str([e["t"] for e in ex]))
    check("marks are stripped from the excerpt text", "[00:" not in "".join(e["text"] for e in ex))

    print("\n[LOCATE]")
    raw = "[00:00:10] hello there >> do you think this is right? >> I think it is right because the evidence says so"
    check("a quote spanning a turn is found", V.locate("do you think this is right? I think it is right", raw) is not None)
    check("a leading [SUBJECT] matches the replaced name",
          V.locate("[SUBJECT] said the evidence says so", "[00:00:01] Tim Walz said the evidence says so indeed") is not None)
    check("an elided quote matches on its longest piece",
          V.locate("a b ... the long part of the quote here", "x the long part of the quote here y") is not None)
    check("a quote not in the transcript is not located", V.locate("words that are not there at all", "nothing to see here") is None)
    check("a quote under four words is not located", V.locate("so it goes", "and so it goes on") is None)
    # The pundits blinder writes [AFFILIATION] for a show or outlet, often several
    # words long. Until 2026-10-11 the matcher knew only [SUBJECT] and [COMPANY],
    # so a blinded quote naming the show could never be placed.
    # Judges often write a quotation inside a quote with single marks where the
    # captions have double ones, and either side may use a curly apostrophe.
    check("single quotation marks in a quote match double ones in the transcript",
          V.locate("people were like, 'Oh, you love war.' They loved it",
                   'people were like, "Oh, you love war." They loved it') is not None)
    check("a curly apostrophe matches a straight one",
          V.locate("it’s what we always said it would be", "it's what we always said it would be") is not None)
    check("an [AFFILIATION] in a blinded quote matches the show it replaced",
          V.locate("we said it on [AFFILIATION] last night again",
                   "[00:00:01] we said it on The Matt Walsh Show last night again") is not None)

    print("\n[SIGNALS]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "t" / "p").mkdir(parents=True)
        (td / "g" / "fable" / "p").mkdir(parents=True)
        text = ("[00:00:00] welcome to the show >> so do you think taxes should go up for everyone? >> "
                "no I think the burden should fall on those who can carry it best and we should say so plainly "
                "[00:05:00] people ask me whether Jane Roe changed her mind and she did not at all ever "
                "and the long answer is that policy matters more than slogans in every single case here")
        (td / "t" / "p" / "s1.json").write_text(json.dumps({"video_id": "v1", "text": text, "yt_title": "T"}))
        ev = [
            {"quote": "so do you think taxes should go up for everyone?", "speaker": "subject"},
            {"quote": "no I think the burden should fall on those who can carry it best", "speaker": "subject"},
            {"quote": "people ask me whether Jane Roe changed her mind", "speaker": "subject"},
            {"quote": "policy matters more than slogans in every single case", "speaker": "subject"},
            {"quote": "welcome to the show and so on here", "speaker": "interlocutor"},
            {"quote": "", "speaker": "subject"},
        ]
        (td / "g" / "fable" / "p" / "s1__fable__blinded__r0.json").write_text(json.dumps({
            "leader_slug": "p", "source_id": "s1", "judge": "fable", "mode": "blinded", "run": 0,
            "grade": {"venue_type": "conversation", "dimensions": {"d1": {"evidence": ev}}}}))
        roster = {"p": {"slug": "p", "name": "Jane Roe", "role": "host", "lean": "SECRET-LEAN"}}
        rows, key, rep = V.suspect_quotes(td / "g", td / "t", roster)
        sigs = {tuple(sorted(v["signals"])) for v in key.values()}
        texts = [c["text"] for r in rows for c in r["quotes"]]
        check("a question inside a conversation is flagged", any("question_in_conversation" in x for x in sigs), str(sigs))
        check("a quote naming the subject is flagged", any("names_subject" in x for x in sigs), str(sigs))
        check("an ordinary answer is not flagged", not any("policy matters" in t for t in texts), str(texts))
        check("a quote the judge gave to someone else is not in the queue", not any("welcome" in t for t in texts))
        check("the scan counts every subject quote it read", rep["subject_quotes"] == 5, str(rep))
        check("an empty quote is counted as empty, not as one the matcher missed",
              rep.get("empty") == 1 and rep["located"] + rep["not_located"] + rep["empty"] == rep["subject_quotes"],
              str(rep))

        print("\n[HIDDEN]")
        page_json = json.dumps(rows)
        check("no judge name or label reaches the page rows",
              '"judge"' not in page_json and '"label"' not in page_json and "fable" not in page_json)
        check("the key holds the judge, mode and label for each flagged quote",
              all(j["judge"] == "fable" and j["label"] == "subject" for v in key.values() for j in v["judges"]))
        check("no lean value reaches the page rows", "SECRET-LEAN" not in page_json)

        print("\n[JOIN]")
        qid = next(iter(key))
        res = V.join_quotes([{"qid": qid, "answer": "other"}], key)
        check("an answer joins its key entry", res["answers"][qid]["answer"] == "other" and res["answers"][qid]["judges"])
        check("the tally counts it", res["tally"]["other"] == 1, str(res["tally"]))
        check("the report says its rates are among flagged quotes only", "FLAGGED" in res["note"])
        try:
            V.join_quotes([{"qid": "p:zz:1", "answer": "subject"}], key)
            check("an answer for a quote not in the key stops the import", False, "accepted")
        except SystemExit as exc:
            check("an answer for a quote not in the key stops the import", "not in the key" in str(exc), str(exc))

    print("\n[PAGE]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "t" / "p").mkdir(parents=True)
        for sid in ("a", "b"):
            (td / "t" / "p" / f"{sid}.json").write_text(json.dumps({
                "video_id": f"vid{sid}", "text": "[00:00:00] Jane Roe said a thing " * 50,
                "yt_duration_sec": 1800, "word_count": 350, "yt_description": "with Jane Roe"}))
        (td / "c.json").write_text(json.dumps({"p/a": {"title": "A", "hints": []}, "p/b": {"title": "B", "hints": []}}))
        (td / "r.json").write_text(json.dumps({"roster": [{"slug": "p", "name": "Jane Roe", "role": "host", "lean": "SECRET-LEAN"}]}))
        V.build(SimpleNamespace(checklist=str(td / "c.json"), transcripts=str(td / "t"),
                                roster=str(td / "r.json"), out=str(td / "o.html"), grades=None, quote_key=None))
        page = (td / "o.html").read_text()
        check("the page carries every recording", '"key": "p/a"' in page and '"key": "p/b"' in page)
        check("and no lean field or value, even when the roster has one",
              "SECRET-LEAN" not in page and '"lean"' not in page)
        check("the data placeholder was replaced", "/*__DATA__*/null" not in page)

    print("\n[SHADOW]")
    # FOUND 2026-09-20 in a real browser: the page grew a module-level `store` holding
    # the save adapter, and `setField(store, id, f, v)` already took a parameter of that
    # name for the labels object. Inside setField the parameter won, so every save died
    # with "store.put is not a function". `node --check` passes it, and no unit test
    # here executes the page, so nothing caught it until a browser ran the save path.
    # The rule is general: a parameter may not hide a module-level binding its own body
    # uses. It is a name collision, and the page has one name per idea.
    src = V.TEMPLATE
    js = src[src.index("const D = "):]
    globals_ = set()
    for decl in re.findall(r"^(?:let|const|var)\s+(.*?);?$", js, re.M):
        # One `let` line declares several names, which is where the real bug sat. Split
        # on commas at bracket depth 0, never on the first `=`: a lazy match to `=`
        # sees only `labels` on `let labels={}, ..., saver=null, ...` and makes this
        # whole check vacuous. That is how the first version of it passed the mutation.
        depth, part, parts = 0, "", []
        for ch in decl:
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(part)
                part = ""
            else:
                part += ch
        parts.append(part)
        for p in parts:
            name = p.split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                globals_.add(name)
    assert {"labels", "attrib", "db", "writable"} <= globals_, f"extraction missed names: {sorted(globals_)}"
    offenders = []
    for m in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)\s*\{", js):
        fname, params = m.group(1), m.group(2)
        names = {re.split(r"[=:]", p)[0].strip() for p in params.split(",") if p.strip()}
        names = {n for n in names if re.fullmatch(r"[A-Za-z_$][\w$]*", n)}
        body = js[m.end():m.end() + 1400]
        for n in names & globals_:
            if re.search(r"\b" + re.escape(n) + r"\s*\.\w", body):
                offenders.append(f"{fname}({n}) hides the module-level {n}")
    check("no function parameter hides a module-level binding its body dereferences",
          not offenders, "; ".join(offenders))

    print("\n[DRAFTS]")
    good = {"subject_present": True, "main_speaker": True, "venue": "solo", "political_content": True,
            "confidence": "high", "reason": "R", "evidence": ["E1"]}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "t" / "p").mkdir(parents=True)
        for sid in ("conf", "unsure", "none", "broken"):
            (td / "t" / "p" / f"{sid}.json").write_text(json.dumps({"video_id": f"v{sid}", "text": "[00:00:00] words " * 40,
                                                                    "yt_duration_sec": 600, "word_count": 80}))
        (td / "c.json").write_text(json.dumps({f"p/{s}": {"title": s, "hints": []} for s in ("conf", "unsure", "none", "broken")}))
        (td / "r.json").write_text(json.dumps({"roster": [{"slug": "p", "name": "Jane Roe", "role": "host"}]}))
        lines = [{"row": 1, "key": "p/conf", "model": "claude-fable-5-1", **good, "confidence": "medium"},
                 {"row": 1, "key": "p/conf", "model": "claude-fable-5-1", **good},
                 {"row": 2, "key": "p/unsure", "model": "claude-fable-5-1", **good, "confidence": "medium"},
                 {"row": 4, "key": "p/broken", "model": "claude-fable-5-1", "error": "ValueError: no JSON"}]
        (td / "d.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
        ns = dict(checklist=str(td / "c.json"), transcripts=str(td / "t"), roster=str(td / "r.json"),
                  out=str(td / "o.html"), grades=None, quote_key=None)
        V.build(SimpleNamespace(**ns, drafts=str(td / "d.jsonl")))
        page = (td / "o.html").read_text()
        got = {r["key"]: r for r in json.loads(page[page.index("const D = ") + 10:page.index(";\nconst VENUE_DEF")]
                                               .replace("<\\/", "</"))["rows"]}
        check("the latest draft wins, and a confident one gives no reason to check first",
              got["p/conf"]["draft"]["confidence"] == "high" and got["p/conf"]["doubt"] == [], str(got["p/conf"].get("doubt")))
        check("a medium-confidence draft is flagged with needs_review's own words",
              got["p/unsure"]["doubt"] == ["model confidence medium"] and got["p/unsure"]["draft"]["model"] == "claude-fable-5-1")
        check("a recording with no draft, or a failed one, shows none and is flagged",
              got["p/none"]["draft"] is None and got["p/none"]["doubt"] == ["no model draft"]
              and got["p/broken"]["draft"] is None and got["p/broken"]["doubt"] == ["the model gave no usable answer"],
              str({k: (got[k]["draft"], got[k]["doubt"]) for k in ("p/none", "p/broken")}))
        check("the page shows the draft's evidence fragments", got["p/conf"]["draft"]["evidence"] == ["E1"])
        V.build(SimpleNamespace(**ns))
        page0 = (td / "o.html").read_text()
        rows0 = json.loads(page0[page0.index("const D = ") + 10:page0.index(";\nconst VENUE_DEF")].replace("<\\/", "</"))["rows"]
        check("without --drafts no row carries a draft or a reason",
              len(rows0) == 4 and not any("draft" in r or "doubt" in r for r in rows0), str([sorted(r) for r in rows0][:1]))
        (td / "d2.jsonl").write_text(json.dumps({"key": "p/elsewhere", "model": "m", **good}) + "\n")
        try:
            V.build(SimpleNamespace(**ns, drafts=str(td / "d2.jsonl")))
            check("a draft for a recording off the checklist stops the build", False, "built")
        except SystemExit as exc:
            check("a draft for a recording off the checklist stops the build", "not on the checklist" in str(exc), str(exc))
    lab = V.to_labels([{"key": "p/a", "subject_present": True, "venue": "solo", "political_content": True,
                        "draft_shown": "claude-fable-5-1"}], {"p/a": {}})["labels"]["p/a"]
    check("an assisted label keeps draft_shown through the import, and report still accepts it",
          lab.get("draft_shown") == "claude-fable-5-1" and P.human_errors(lab) == [], str(lab))
    lab0 = V.to_labels([{"key": "p/a", "subject_present": True, "venue": "solo", "political_content": True}],
                       {"p/a": {}})["labels"]["p/a"]
    check("a blind label gains no draft_shown", "draft_shown" not in lab0, str(lab0))

    print("\n[RENDER]")
    base = {"slug": "p", "role": "", "title": "T", "channel": "c", "url": "", "video_id": "v", "duration": 600,
            "words": 100, "hints": [], "description": "", "forms": ["Jane Roe"], "mentions": 1, "excerpts": []}
    shown = {**good, "model": "claude-fable-5-1"}
    rows = [{**base, "key": "p/conf", "sid": "conf", "person": "Ann Able", "upload": "20240101", "draft": shown, "doubt": []},
            {**base, "key": "p/unsure", "sid": "unsure", "person": "Zed Zulu", "upload": "20240101",
             "draft": {**shown, "confidence": "medium"}, "doubt": ["model confidence medium"]},
            {**base, "key": "p/absent", "sid": "absent", "person": "Ann Able", "upload": "20240202",
             "draft": {**shown, "subject_present": False}, "doubt": ["model says the subject is absent"]}]
    r = run_page(rows)
    order = [a or b for a, b in re.findall(r'class="sec"[^>]*>([^<]+?) <small|data-k="([^"]+)"', r["list"])]
    check("flagged recordings come first under their own section, whatever the surname, and one person's "
          "confident recording stays in the confident section",
          order == ["Check first", "p/absent", "p/unsure", "Model was confident", "p/conf"], f"{order} {r.get('threw', '')}")
    check("the first recording shown is the flagged one, with the draft card and a model tag on each drafted answer",
          "Model draft" in r["detail"] and "model says the subject is absent" in r["detail"]
          and r["detail"].count('class="mtag"') == 3, r["detail"][:300])
    post = r["posts"][0] if r["posts"] else {}
    check("an answer saved with a draft on screen carries draft_shown",
          post.get("kind") == "labels" and post.get("id") == "p/absent"
          and post.get("value", {}).get("draft_shown") == "claude-fable-5-1"
          and post["value"].get("subject_present") is True, str(r["posts"]))
    r0 = run_page([{k: v for k, v in x.items() if k not in ("draft", "doubt")} for x in rows])
    order0 = [a or b for a, b in re.findall(r'class="sec"[^>]*>([^<]+?) <small|data-k="([^"]+)"', r0["list"])]
    check("a page without drafts has no sections and keeps surname order, and saves no draft_shown",
          order0 == ["p/conf", "p/absent", "p/unsure"] and r0["posts"] and "draft_shown" not in r0["posts"][0]["value"],
          f"{order0} {r0['posts']}")
    check("the page's script throws nothing, with drafts or without", r["threw"] == "" and r0["threw"] == "",
          f"{r['threw']!r} {r0['threw']!r}")
    check("each section header counts only its own recordings",
          "Check first <small>· 0 of 2 checked</small>" in r["list"]
          and "Model was confident <small>· 0 of 1 checked</small>" in r["list"],
          str(re.findall(r'class="sec"[^>]*>(.*?)</div>', r["list"])))
    check("the draft card quotes the draft's evidence", "<blockquote>E1</blockquote>" in r["detail"], r["detail"][:600])
    other = next(v for v in V.VENUES if v != "solo")
    # Partial answers, so the recording stays first in the to-do list and its card is the one shown.
    rd = run_page(rows, {"labels": {"p/absent": {"subject_present": True, "venue": other}}, "attribution": {}})
    check("where a saved answer differs from the draft, the card names each field that differs, and only those",
          "model says the subject is absent" in rd["detail"]
          and "differs from the model's on: subject present, format</div>" in rd["detail"] and rd["threw"] == "",
          re.sub(r"\s+", " ", rd["detail"])[:900])
    ra = run_page(rows, {"labels": {"p/absent": {"subject_present": False, "venue": other}}, "attribution": {}})
    check("where the person also says the subject is absent, a different format is no disagreement (as in needs_review)",
          "model says the subject is absent" in ra["detail"] and "Model draft" in ra["detail"]
          and "differs" not in ra["detail"] and ra["threw"] == "", re.sub(r"\s+", " ", ra["detail"])[:900])
    nd = run_page([{**base, "key": "p/nodraft", "sid": "nodraft", "person": "Ann Able", "upload": "20240101",
                    "draft": None, "doubt": ["no model draft"]}, rows[0]])
    order_nd = [a or b for a, b in re.findall(r'class="sec"[^>]*>([^<]+?) <small|data-k="([^"]+)"', nd["list"])]
    check("a recording with no usable draft goes under Check first and shows a card that says so, with its reason",
          order_nd == ["Check first", "p/nodraft", "Model was confident", "p/conf"]
          and "No usable model draft" in nd["detail"] and '<span class="chip">no model draft</span>' in nd["detail"]
          and 'class="mtag"' not in nd["detail"] and nd["threw"] == "", f"{order_nd} {nd['detail'][:400]}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
