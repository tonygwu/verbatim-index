#!/usr/bin/env python3
"""Speaker-range persistence: drafts stay separate, stale/invalid offsets cannot save."""
import copy
import json
import tempfile
import threading
import unittest
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
            self.assertEqual(json.load(response), self.transcript)
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


if __name__ == '__main__': unittest.main()
