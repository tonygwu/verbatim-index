#!/usr/bin/env python3
"""Isolated browser check of the annotation page; synthetic data only. Requires Playwright + Chromium.

Outside the globbed gate because it needs a browser. Run it after any change to the
page's JavaScript. It serves two sessions at once, as `annotations.py serve` does:
a pundits session (checklist, speakers, captions, with judge suggestions) driven
through real drags, saves, reloads and corrections, and an insights + predictions
session whose one recording carries both projects.

.venv/bin/python scripts/check_annotations_ui.py
"""
import json
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from playwright.sync_api import sync_playwright
import annotations as C
from annotations_serve import build_server
from annotations_spans import token_kinds
from annotations_store import Session
from test_annotations_select import make_data


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True)


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)/'data'
        (root/'transcripts'/'p').mkdir(parents=True); (root/'grades'/'fable'/'p').mkdir(parents=True)
        (root/'roster').mkdir(); (root/'.study').write_text('pundits\n')
        raw = '[00:00:05] Intro from our host here >> I disagree with that point >> Another reply from the host >> I stand by this second answer now [00:06:06] Extra [ __ ] words ... here'
        record = {'text': raw, 'video_id': 'fixture', 'yt_title': 'Speaker range fixture', 'yt_duration_sec': 600}
        (root/'transcripts'/'p'/'a.json').write_text(json.dumps(record))
        (root/'transcripts'/'p'/'b.json').write_text(json.dumps(record))
        (root/'roster'/'final.json').write_text(json.dumps({'roster':[{'slug':'p','name':'Jane Roe'}]}))
        (root.parent/'checklist.json').write_text(json.dumps({'p/a':{}, 'p/b':{}}))
        grade = {'leader_slug':'p','source_id':'a','judge':'fable','mode':'open','run':0,'grade':{'venue_type':'conversation','dimensions':{'d1':{'evidence':[
            {'quote':'I disagree with that point?', 'speaker':'subject'},
            {'quote':'Intro from our host here', 'speaker':'interlocutor'}]}}}}
        (root/'grades'/'fable'/'p'/'a__fable__open__r0.json').write_text(json.dumps(grade))
        git(root,'init','-q'); git(root,'remote','add','origin','git@example.invalid:t/verbatim-pundits-data.git')
        git(root,'add','-A'); git(root,'-c','user.email=t@t','-c','user.name=t','commit','-qm','x')
        C.build(SimpleNamespace(project=['pundits'],data=str(root),out=str(root/'p6'),name=None,keys=None,reasons=None,cap=6,
                                checklist=str(root.parent/'checklist.json'),grades=True,drafts=None))
        answers=root/'p6'/'human_answers.json'
        lead=Path(td)/'leaders'; lead.mkdir(); make_data(lead)
        C.build(SimpleNamespace(project=['insights','predictions'],data=str(lead),out=str(lead/'both'),name=None,
                                keys='jane-roe/talk-1',reasons=None,cap=6,checklist=None,grades=False,drafts=None))
        httpd=build_server([Session.open(root/'p6'),Session.open(lead/'both')],0)
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1100})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{httpd.server_port}/');page.wait_for_load_state('networkidle')
                assert page.locator('a[href="/s/p6/"]').count()==1 and page.locator('a[href="/s/both/"]').count()==1
                page.locator('a[href="/s/p6/"]').click();page.wait_for_load_state('networkidle')
                page.screenshot(path='/tmp/annotations-span-initial.png',full_page=True)
                assert not errors, errors
                editor=page.locator('[data-span-editor="0"]')
                editor.locator('.word').first.wait_for()
                page.screenshot(path='/tmp/annotations-span-before.png',full_page=True)
                assert editor.get_by_text('Confirm suggested spans in this passage',exact=True).is_enabled()
                assert not answers.exists(), 'Drafts were saved without human confirmation'
                assert page.get_by_text('Quick answer for this quote only',exact=True).count()==0
                assert page.get_by_role('button',name='Use reviewed markings to answer this quote',exact=True).count()==0
                assert '5 quote words still need review' in editor.locator('.quote-summary').inner_text()
                for i,kind in enumerate(token_kinds(raw.split())):
                    if kind!='speech':assert editor.locator(f'[data-w="{i}"]').count()==0
                assert editor.locator('.caption-gap').count()>0
                page.keyboard.press('y')
                page.wait_for_function('document.getElementById("status").textContent!=="Saving…"')
                assert json.loads(answers.read_text())['labels']['p/a']['subject_present'] is True
                editor.locator('.word').first.wait_for()
                # Real mouse drag, not a call to the application's range functions.
                first=editor.locator('[data-w="7"]'); last=editor.locator('[data-w="9"]')
                first.scroll_into_view_if_needed();a=first.bounding_box();b=last.bounding_box()
                page.mouse.move(a['x']+1,a['y']+a['height']/2);page.mouse.down()
                page.mouse.move(b['x']+b['width']-1,b['y']+b['height']/2,steps=12);page.mouse.up()
                editor.get_by_role('button',name='Mark as Jane Roe',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                stored=json.loads(answers.read_text())['spans']['p/a']['ranges']
                assert stored==[{'start':7,'end':10,'speaker':'subject','origin':'human'}],stored
                assert '2 quote words still need review' in editor.locator('.quote-summary').inner_text()
                assert json.loads(answers.read_text())['attribution']['p:a:7']['answer'] is None
                # Select a second, disjoint passage through DOM Selection, exercising
                # the same mouseup handler (also used by keyboard text selection).
                def select_words(a,b):
                    editor.locator('.span-transcript').evaluate('''(node, bounds)=>{
                      const range=document.createRange();range.setStart(node.querySelector('[data-w="'+bounds[0]+'"]').firstChild,0);
                      const end=node.querySelector('[data-w="'+(bounds[1]-1)+'"]').firstChild;range.setEnd(end,end.length);
                      const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
                      node.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                    }''',[a,b])
                select_words(19,26);editor.get_by_role('button',name='Mark as Jane Roe',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert len(json.loads(answers.read_text())['spans']['p/a']['ranges'])==2
                # Shrink the second span; the removed tail must not remain marked.
                editor.locator('.span-ranges summary').click()
                editor.get_by_role('button',name='Select / adjust').nth(1).click()
                slider=editor.get_by_role('slider',name='Selection end word')
                slider.fill('23');editor.get_by_role('button',name='Mark as Jane Roe',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert json.loads(answers.read_text())['spans']['p/a']['ranges'][-1]['end']==23
                editor.get_by_role('button',name='Undo marking',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert json.loads(answers.read_text())['spans']['p/a']['ranges'][-1]['end']==26
                editor.get_by_role('button',name='Expand to full transcript',exact=True).click()
                assert editor.locator('.word').count()==token_kinds(raw.split()).count('speech')
                assert editor.locator('.caption-time').count()==2
                editor.get_by_role('button',name='Back to passage',exact=True).click()
                editor.get_by_role('button',name='Confirm suggested spans in this passage',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                ranges=json.loads(answers.read_text())['spans']['p/a']['ranges']
                assert any(r['speaker']=='other' and r['origin']=='model_confirmed' for r in ranges)
                assert any(r['start']==7 and r['origin']=='human' for r in ranges)
                page.wait_for_function('Object.values(attrib).some(v=>v.answer==="subject")')
                page.wait_for_function('document.getElementById("status").textContent!=="Saving…"')
                page.reload();page.wait_for_load_state('networkidle')
                page.locator('[data-k="p/a"]').click();editor.locator('.reviewed').first.wait_for()
                assert page.evaluate('humanRanges(REC["p/a"]).length')==len(ranges)
                # Explicit other span within the quote produces Both, not Subject.
                select_words(10,12);editor.get_by_role('button',name='Someone else',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                page.wait_for_function('Object.values(attrib).some(v=>v.answer==="both")')
                assert 'Quote includes both speakers' in editor.locator('.quote-summary').inner_text()
                # Clearing words reopens review instead of reporting Can't tell.
                editor.get_by_role('button',name='Clear human marks',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert json.loads(answers.read_text())['attribution']['p:a:7']['answer'] is None
                editor.get_by_role('button',name='Review remaining quote words',exact=True).click()
                editor.get_by_role('button',name='Unsure',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert json.loads(answers.read_text())['attribution']['p:a:7']['answer']=='unclear'
                assert 'Quote reviewed — speaker uncertain' in editor.locator('.quote-summary').inner_text()
                # A selection across a gap and an ellipsis counts actual words only.
                select_words(27,34)
                selection=editor.locator('.span-selection').inner_text()
                assert selection=='Selected 3 words: Extra words here',selection
                editor.get_by_role('button',name='Someone else',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert json.loads(answers.read_text())['attribution']['p:a:7']['answer']=='unclear'
                page.screenshot(path='/tmp/annotations-span-after.png',full_page=True)
                # Replace two caption words with a longer phrase, retaining original
                # speaker offsets and original evidence text across save/reload/restore.
                before_ranges=json.loads(answers.read_text())['spans']['p/a']['ranges']
                before_quote=page.locator('.quote-exact').inner_text()
                select_words(10,12)
                editor.get_by_role('button',name='Correct text',exact=True).click()
                editor.get_by_label('What was actually said?').fill('the abortion argument')
                editor.get_by_role('button',name='Save correction',exact=True).click()
                page.wait_for_function('correctionAnswers["p/a"]?.revision===1 && !correctionPending["p/a"]')
                assert editor.locator('[data-w="10"]').inner_text().strip()=='the abortion argument'
                assert editor.locator('[data-w="10"]').get_attribute('data-end')=='12'
                assert json.loads(answers.read_text())['spans']['p/a']['ranges']==before_ranges
                assert page.locator('.quote-exact').inner_text()==before_quote
                page.screenshot(path='/tmp/annotations-text-corrected.png',full_page=True)
                page.reload();page.wait_for_load_state('networkidle');page.locator('[data-k="p/a"]').click()
                editor.locator('.word.corrected').wait_for()
                assert editor.locator('.word.corrected').inner_text().strip()=='the abortion argument'
                # Selecting even part of a replacement labels the entire anchored phrase.
                editor.locator('[data-w="10"]').evaluate('''node=>{
                    const r=document.createRange();r.selectNodeContents(node);
                    const s=window.getSelection();s.removeAllRanges();s.addRange(r);
                    node.closest('.span-transcript').dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                }''')
                editor.get_by_role('button',name='Someone else',exact=True).click()
                page.wait_for_function('spanPending["p/a"]===0')
                assert any(r['start']==10 and r['end']==12 and r['speaker']=='other'
                           for r in json.loads(answers.read_text())['spans']['p/a']['ranges'])
                editor.locator('.text-corrections summary').click()
                editor.get_by_role('button',name='Restore original',exact=True).click()
                page.wait_for_function('correctionAnswers["p/a"]?.revision===2 && !correctionPending["p/a"]')
                assert editor.locator('.word.corrected').count()==0
                assert len(json.loads(answers.read_text())['corrections']['p/a']['history'])==2
                # Non-graded recording: no invented suggestions and optional full editor.
                page.locator('[data-k="p/b"]').click()
                page.get_by_text('Mark speaker ranges in this recording (optional)',exact=True).click()
                page.locator('[data-span-editor="-1"] .word').first.wait_for()
                assert 'No model suggestions' in page.locator('[data-span-editor="-1"]').inner_text()
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path='/tmp/annotations-span-mobile.png',full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                assert not errors, errors
                # The insights + predictions session: one recording, both tags, both projects' quotes.
                page.set_viewport_size({'width':1440,'height':1100})
                both=lead/'both'/'human_answers.json'
                page.goto(f'http://127.0.0.1:{httpd.server_port}/s/both/');page.wait_for_load_state('networkidle')
                assert not errors, errors
                assert page.locator('#list .pchip').count()==2
                assert page.locator('.qitem .pchip', has_text='predictions').count()==1
                assert page.locator('.qitem .pchip', has_text='insights').count()>=1
                assert page.locator('[data-mode="checklist"]').count()==0
                page.locator('#projects button[data-project="predictions"]').click()
                assert page.locator('#list .item[data-k="jane-roe/talk-1"]').count()==1
                first=page.locator('[data-span-editor="0"]');first.locator('.word').first.wait_for()
                assert 'No model suggestions' in first.inner_text()
                w=first.locator('.word.evidence')
                w.first.scroll_into_view_if_needed();a=w.first.bounding_box();b=w.last.bounding_box()
                page.mouse.move(a['x']+1,a['y']+a['height']/2);page.mouse.down()
                page.mouse.move(b['x']+b['width']-1,b['y']+b['height']/2,steps=12);page.mouse.up()
                first.get_by_role('button',name='Mark as Jane Roe',exact=True).click()
                page.wait_for_function('spanPending["jane-roe/talk-1"]===0')
                saved=json.loads(both.read_text())
                assert list(saved['spans'])==['jane-roe/talk-1'] and saved['spans']['jane-roe/talk-1']['assisted'] is False
                assert saved['labels']=={}
                assert not errors, errors
                page.screenshot(path='/tmp/annotations-two-projects.png',full_page=True)
                browser.close()
            print('PASS: landing page lists both sessions; real drag, disjoint spans, caption markers skipped, automatic quote results, correction save/reload/restore, stable speaker anchors, incomplete vs unsure, full transcript and mobile layout; a two-project recording shows both tags and quotes, filters by project, has no checklist, and saves a blind (not assisted) range; synthetic data only.')
        finally:
            httpd.shutdown();httpd.server_close()


if __name__=='__main__':main()
