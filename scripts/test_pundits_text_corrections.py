"""Caption correction persistence, stable anchors and conflict handling."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from pundits_speaker_spans import build_transcript, sidecar_path
from pundits_text_corrections import validate_corrections, update_corrections, corrected_text, export_corrections
from pundits_verify_serve import build_server


class Corrections(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transcript = build_transcript('p/a', '[00:00:01] How does this apply to the the Bush argument again? >> Reply here', [])
        self.edit = {'start': 6, 'end': 9, 'original': 'the the Bush', 'replacement': 'the abortion'}
        self.value = {k:self.transcript[k] for k in ('key','text_sha256','token_count')}
        self.value.update(edits=[self.edit], checked_by='operator', revision=0)

    def test_replacement_changes_word_count_without_mutating_source(self):
        before=copy.deepcopy(self.transcript)
        value=update_corrections(self.value,None,self.transcript)
        self.assertIn('apply to the abortion argument',corrected_text(self.transcript,value))
        self.assertEqual(self.transcript,before)
        self.assertEqual((value['edits'][0]['start'],value['edits'][0]['end']),(6,9))

    def test_validation_rejects_wrong_source_overlap_and_metadata(self):
        for kind in ('stale','overlap','original','empty','bounds','boolean','timestamp','gap'):
            value=copy.deepcopy(self.value)
            if kind=='stale':value['text_sha256']='old'
            elif kind=='overlap':value['edits'].append(copy.deepcopy(self.edit))
            elif kind=='original':value['edits'][0]['original']='wrong'
            elif kind=='empty':value['edits'][0]['replacement']=' '
            elif kind=='bounds':value['edits'][0]['end']=999
            elif kind=='boolean':value['edits'][0]['start']=True
            else:value['edits'][0].update(start=0 if kind=='timestamp' else 11,end=12)
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_corrections(value,self.transcript)

    def test_revisions_and_restore_history(self):
        first=update_corrections(self.value,None,self.transcript)
        with self.assertRaisesRegex(ValueError,'another window'):update_corrections(self.value,first,self.transcript)
        restored=update_corrections({**self.value,'revision':1,'edits':[],'history':['forged']},first,self.transcript)
        self.assertEqual(restored['history'][1]['before'],[self.edit])
        self.assertEqual(restored['edits'],[])
        self.assertEqual(len(restored['history']),2)
        self.assertEqual(corrected_text(self.transcript,restored),' '.join(self.transcript['tokens']))

    def test_http_roundtrip_preserves_labels_ranges_and_original_evidence(self):
        page=self.root/'page.html'; answers=self.root/'answers.json'
        data={'rows':[{'key':'p/a'}],'transcript_index':{'p/a':{}},'quote_rows':[
            {'key':'p/a','quotes':[{'qid':'p:a:6','quote_start':6,'quote_end':9,'text':'the the Bush'}]}]}
        page.write_text('const D = '+json.dumps(data)+';\n')
        side=sidecar_path(page,'p/a');side.parent.mkdir(parents=True);side.write_text(json.dumps(self.transcript))
        annotation={k:self.transcript[k] for k in ('key','text_sha256','token_count')}
        annotation.update(checked_by='operator',ranges=[{'start':6,'end':9,'speaker':'other','origin':'human'}])
        original={'labels':{'p/a':{'subject_present':True}},'attribution':{},'spans':{'p/a':annotation}}
        answers.write_text(json.dumps(original));source=side.read_bytes();page_before=page.read_bytes()
        server=build_server(page,answers,0);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        def post(value):
            req=Request(base+'/api/answer',data=json.dumps({'kind':'corrections','id':'p/a','value':value}).encode(),headers={'Content-Type':'application/json'})
            with urlopen(req) as r:return json.load(r)
        response=post(self.value)
        self.assertEqual(response['correction']['revision'],1)
        with urlopen(base+'/api/answers') as r:loaded=json.load(r)
        self.assertEqual(loaded['spans'],original['spans']);self.assertEqual(loaded['labels'],original['labels'])
        self.assertEqual(loaded['attribution']['p:a:6']['answer'],'other')
        self.assertEqual(loaded['corrections']['p/a']['edits'],[self.edit])
        before=answers.read_bytes()
        with self.assertRaises(HTTPError) as caught:post(self.value)
        self.assertEqual(caught.exception.code,409);self.assertEqual(answers.read_bytes(),before)
        output=self.root/'export.json';result=export_corrections(answers,page,output)
        self.assertIn('the abortion argument',result['recordings']['p/a']['corrected_text'])
        self.assertEqual(side.read_bytes(),source);self.assertEqual(page.read_bytes(),page_before)
        post({**self.value,'revision':1,'edits':[]})
        disk=json.loads(answers.read_text())
        self.assertEqual(disk['corrections']['p/a']['edits'],[])
        self.assertEqual(disk['spans'],original['spans'])


if __name__=='__main__':unittest.main()
