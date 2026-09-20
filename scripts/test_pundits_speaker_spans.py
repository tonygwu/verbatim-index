#!/usr/bin/env python3
"""Speaker-range persistence: drafts stay separate, stale/invalid offsets cannot save."""
import copy
import json
import tempfile
import threading
import unittest
import pundits_speaker_spans as spans
import urllib.error
import urllib.request
from pathlib import Path

from pundits_speaker_spans import build_transcript, import_spans, sidecar_path, validate_annotation
from pundits_verify_serve import build_server


class SpeakerSpans(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = '[00:00:05] Intro from our host here >> I disagree with that point >> Another reply from the host'
        self.grade = self.root / 'grade.json'
        self.record = {'judge': 'fable', 'mode': 'open', 'run': 0, 'grade': {'dimensions': {'d1': {'evidence': [
            {'quote': 'I disagree with that point', 'speaker': 'subject'},
            {'quote': 'Intro from our host here', 'speaker': 'interlocutor'},
        ]}}}}
        self.grade.write_text(json.dumps(self.record))
        self.transcript = build_transcript('p/a', self.raw, [(self.grade, self.record)])
        self.value = {'key': 'p/a', 'text_sha256': self.transcript['text_sha256'],
                      'token_count': self.transcript['token_count'], 'checked_by': 'operator',
                      'ranges': [{'start': 7, 'end': 12, 'speaker': 'subject', 'origin': 'human'},
                                 {'start': 13, 'end': 18, 'speaker': 'other', 'origin': 'model_confirmed'}]}

    def test_drafts_have_real_provenance_and_do_not_fill_unknown_text(self):
        self.assertEqual([(r['start'], r['end'], r['speaker']) for r in self.transcript['suggestions']],
                         [(7, 12, 'subject'), (1, 6, 'other')])
        self.assertTrue(all(r['grade_sha256'] for r in self.transcript['suggestions']))
        self.assertNotIn('ranges', self.transcript)
        self.assertFalse(any(r['start'] <= 13 < r['end'] for r in self.transcript['suggestions']))

    def test_repeated_quote_not_arbitrarily_positioned(self):
        result = build_transcript('p/a', self.raw + ' I disagree with that point', [(self.grade, self.record)])
        self.assertEqual([s['speaker'] for s in result['suggestions']], ['other'])
        self.assertEqual(result['unlocated_or_ambiguous'], 1)

    def test_hash_and_ranges_fail_closed(self):
        validate_annotation(self.value, self.transcript)
        for mutation in ('hash', 'overlap', 'past_end', 'negative', 'empty', 'float', 'bool', 'draft'):
            value = copy.deepcopy(self.value)
            if mutation == 'hash': value['text_sha256'] = 'old'
            elif mutation == 'overlap': value['ranges'][1]['start'] = 10
            elif mutation == 'past_end': value['ranges'][-1]['end'] = 999
            elif mutation == 'negative': value['ranges'][0]['start'] = -1
            elif mutation == 'empty': value['ranges'][0]['end'] = 7
            elif mutation == 'float': value['ranges'][0]['start'] = 7.0
            elif mutation == 'bool': value['ranges'][0]['start'] = True
            else: value['ranges'][0]['origin'] = 'model_draft'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_annotation(value, self.transcript)

    def test_path_cannot_escape_sidecars(self):
        for key in ('../secret', 'p/../../secret', '/tmp/x', 'p/a.json'):
            with self.assertRaises(ValueError): sidecar_path(self.root / 'page.html', key)

    def test_caption_markers_are_not_speech(self):
        tokens = '[00:06:06] Hello [ __ ] there ... >> goodbye [ ___'.split()
        self.assertEqual(spans.token_kinds(tokens),
                         ['timestamp','speech','gap','gap','gap','speech','gap','turn','speech','gap','gap'])
        self.assertEqual(spans.token_kinds('[Music] really 2024 was good'.split()),
                         ['gap','speech','speech','speech','speech'])

    def test_unreviewed_quote_is_incomplete_not_unclear(self):
        quote = {'quote_start': 7, 'quote_end': 12}
        value = copy.deepcopy(self.value)
        value['ranges'] = [{'start': 1, 'end': 6, 'speaker': 'other', 'origin': 'human'}]
        review = spans.quote_review(quote, self.transcript, value)
        self.assertEqual((review['answer'],review['review_status'],review['unreviewed_words']),
                         (None,'incomplete',5))
        value['ranges'] = [{'start': 7, 'end': 12, 'speaker': 'unclear', 'origin': 'human'}]
        review = spans.quote_review(quote, self.transcript, value)
        self.assertEqual((review['answer'],review['review_status']),('unclear','complete'))

    def test_review_ignores_gaps_and_surrounding_speakers(self):
        transcript = build_transcript('p/a','[00:01:00] Hello [ __ ] there >> outside',[])
        value = {'key':'p/a','text_sha256':transcript['text_sha256'], 'token_count':transcript['token_count'],
                 'checked_by':'operator', 'ranges':[
                    {'start':1,'end':2,'speaker':'other','origin':'human'},
                    {'start':5,'end':6,'speaker':'other','origin':'human'},
                    {'start':7,'end':8,'speaker':'subject','origin':'human'}]}
        review = spans.quote_review({'quote_start':0,'quote_end':7},transcript,value)
        self.assertEqual((review['answer'],review['total_words'],review['unreviewed_words']),('other',2,0))

    def test_roundtrip_keeps_legacy_answers_and_imports_only_human_ranges(self):
        page = self.root / 'page.html'
        page.write_text('const D = ' + json.dumps({'rows': [{'key': 'p/a'}], 'transcript_index': {'p/a': {}}}) + ';\n')
        side = sidecar_path(page, 'p/a'); side.parent.mkdir(parents=True)
        side.write_text(json.dumps(self.transcript))
        answers = self.root / 'human_answers.json'
        legacy = {'labels': {'p/a': {'subject_present': True}}, 'attribution': {'old': {'answer': 'other'}}}
        answers.write_text(json.dumps(legacy))
        server = build_server(page, answers, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        def post(value):
            req = urllib.request.Request(base + '/api/answer', data=json.dumps({'kind': 'spans', 'id': 'p/a', 'value': value}).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response: return json.load(response)
        self.assertTrue(post(self.value)['ok'])
        stored = json.loads(answers.read_text())
        self.assertEqual(stored['labels'], legacy['labels'])
        self.assertEqual(stored['attribution'], legacy['attribution'])
        self.assertEqual(stored['spans']['p/a'], self.value)
        with urllib.request.urlopen(base + '/api/transcript?key=p%2Fa') as response:
            payload = json.load(response)
            self.assertEqual(payload, {**self.transcript, 'token_kinds':spans.token_kinds(self.transcript['tokens'])})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + '/api/transcript?key=..%2Fsecret')
        before = answers.read_bytes()
        with self.assertRaises(urllib.error.HTTPError): post({**self.value, 'text_sha256': 'stale'})
        self.assertEqual(answers.read_bytes(), before)
        result = import_spans(answers, page, self.root / 'imported.json')
        self.assertEqual(result['recordings']['p/a']['ranges'][0]['text'], 'I disagree with that point')
        self.assertEqual(len(result['recordings']['p/a']['ranges']), 2)
        stored['spans']['p/a']['text_sha256'] = 'bad'
        answers.write_text(json.dumps(stored)); prior = (self.root / 'imported.json').read_bytes()
        with self.assertRaises(ValueError): import_spans(answers, page, self.root / 'imported.json')
        self.assertEqual((self.root / 'imported.json').read_bytes(), prior)

    def test_atomic_quote_result_and_legacy_pending_projection(self):
        import pundits_verify_page as verify
        from types import SimpleNamespace
        page = self.root / 'page.html'
        quote = {'qid':'p:a:7','quote_start':7,'quote_end':12}
        page.write_text('const D = ' + json.dumps({'rows':[{'key':'p/a'}], 'transcript_index':{'p/a':{}},
                        'quote_rows':[{'key':'p/a','quotes':[quote]}]}) + ';\n')
        side = sidecar_path(page, 'p/a');side.parent.mkdir(parents=True);side.write_text(json.dumps(self.transcript))
        answers = self.root / 'human_answers.json'
        value = copy.deepcopy(self.value);value['ranges'] = value['ranges'][1:]
        original = {'labels':{},'attribution':{'p:a:7':{'qid':'p:a:7','answer':'unclear'}},'spans':{'p/a':value}}
        answers.write_text(json.dumps(original));before=answers.read_bytes()
        server=build_server(page,answers,0);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(base+'/api/answers') as response: loaded=json.load(response)
        self.assertIsNone(loaded['attribution']['p:a:7']['answer'])
        self.assertEqual(loaded['attribution']['p:a:7']['legacy_answer'],'unclear')
        self.assertEqual(loaded['spans'],original['spans'])
        self.assertEqual(answers.read_bytes(),before,'GET rewrote original human data')
        # Even without another save, import must not count legacy unreviewed words as an uncertain human decision.
        key=self.root/'key.json';key.write_text(json.dumps({'p:a:7':{'signals':[],'judges':[]}}))
        out=self.root/'quote_report.json'
        verify.do_import_quotes(SimpleNamespace(export=str(answers),page=str(page),key=str(key),out=str(out)))
        self.assertEqual(json.loads(out.read_text())['unanswered'],['p:a:7'])
        def post(kind, value):
            req=urllib.request.Request(base+'/api/answer',data=json.dumps({'kind':kind,'id':'p/a' if kind=='spans' else 'p:a:7','value':value}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:return json.load(response)
        result=post('spans',self.value)
        self.assertEqual(result['attribution']['p:a:7']['answer'],'subject')
        disk=json.loads(answers.read_text())
        self.assertEqual(disk['spans']['p/a'],self.value)
        self.assertEqual(disk['attribution']['p:a:7']['answer'],'subject')
        # A stale browser's old manual answer controls cannot contradict ranges.
        with self.assertRaises(urllib.error.HTTPError) as caught:post('attribution',{'answer':'other'})
        self.assertEqual(caught.exception.code,409)
        value['ranges']=[{'start':7,'end':9,'speaker':'subject','origin':'human'}]
        result=post('spans',value)
        self.assertEqual(result['attribution']['p:a:7']['unreviewed_words'],3)
        self.assertIsNone(json.loads(answers.read_text())['attribution']['p:a:7']['answer'])


if __name__ == '__main__': unittest.main()
