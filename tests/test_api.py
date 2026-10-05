import os
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from backend import app


class GradingApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(os.environ, {
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_BASE_URL': 'https://www.su8.codes/v1/',
            'OPENAI_MODEL': 'gpt-5.5',
            # These tests mock httpx.post; production streaming must not bypass it.
            'AI_STREAM': '0',
            'AI_FORMAT_ATTEMPTS': '2',
            'AI_STRUCTURED_OUTPUT': '0',
        })
        self.settings.start()
        self.addCleanup(self.settings.stop)
        prepared = patch.object(app.review_translation, 'prepare_translations', return_value={})
        prepared.start()
        self.addCleanup(prepared.stop)

    def response(self, status, body):
        return httpx.Response(status, json=body, request=httpx.Request(
            'POST', 'https://www.su8.codes/v1/responses'))

    def test_retry_button_eligibility_matches_endpoint_guards(self):
        row = dict(id='job', filename='essay.docx', status='failed', stage='error',
                   error='incomplete', created=0, updated=0, is_demo=0,
                   ai_uncertain=0, attempts=1, quota_state='released')
        self.assertTrue(app.saas.public_job(row)['retryable'])
        for change in ({'status':'succeeded'}, {'ai_uncertain':1},
                       {'attempts':3}, {'quota_state':'committed'}):
            with self.subTest(change=change):
                self.assertFalse(app.saas.public_job(dict(row, **change))['retryable'])

    def test_configured_endpoint_and_output(self):
        grading = app.mock_grading(['Essay'])
        response = self.response(200, {'output': [{'content': [
            {'type': 'output_text', 'text': grading}]}]})
        with patch('httpx.post', return_value=response) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_args.args[0], 'https://www.su8.codes/v1/responses')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(post.call_args.kwargs['json']['model'], 'gpt-5.5')
        # A short essay must not resend the full coding skill and five overlapping references.
        payload = post.call_args.kwargs['json']
        self.assertLess(len(json.dumps(payload, ensure_ascii=False)), 15000)
        self.assertEqual(json.loads(payload['input'][1]['content'])['paragraphs'], ['Essay'])

    def test_invalid_format_is_repaired_before_returning(self):
        grading = app.mock_grading(['Essay'])
        with patch('httpx.post', side_effect=[
            self.response(200, {'output_text': '**段落点评：** 缺少原文'}),
            self.response(200, {'output_text': grading}),
        ]) as post:
            self.assertEqual(app.call_openai('## Essay\n\nEssay\n'), grading)
        self.assertEqual(post.call_count, 2)

    def test_chinese_feedback_is_repaired_to_english(self):
        grading = app.mock_grading(['Essay'])
        chinese = grading.replace('Demo only: actual feedback must be based on the essay.', '点评不能继续默认中文。', 1)
        with patch('httpx.post', side_effect=[self.response(200, {'output_text': chinese}),
                                            self.response(200, {'output_text': grading})]) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_count, 2)

    def test_second_format_repair_can_complete_report(self):
        grading = app.mock_grading(['Essay'])
        with patch.dict(os.environ, {'AI_FORMAT_ATTEMPTS': '3'}), patch('httpx.post', side_effect=[
            self.response(200, {'output_text': 'invalid first report'}),
            self.response(200, {'output_text': 'invalid repaired report'}),
            self.response(200, {'output_text': grading}),
        ]) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_count, 3)

    def test_chinese_annotation_comment_is_repaired(self):
        item=dict(paragraph=1,level='sentence',quote='He go.',kind='error',comment='应使用 goes。',correction='He goes.')
        english=dict(item,comment='Use goes with the singular subject He.')
        with patch('httpx.post', side_effect=[self.response(200, {'output_text': json.dumps([item])}),
                                            self.response(200, {'output_text': json.dumps([english])})]) as post:
            self.assertEqual(app.call_openai('He go.',channel='annotations')[0]['comment'],english['comment'])
        self.assertEqual(post.call_count,2)

    def test_unmarked_rewrite_is_never_accepted(self):
        grading = app.mock_grading(['A changed sentence.'])
        with patch('httpx.post', return_value=self.response(200, {'output_text': grading})) as post:
            with self.assertRaisesRegex(RuntimeError, '原始作文已保留'):
                app.call_openai('## Essay\n\nAn original sentence.\n')
        self.assertEqual(post.call_count, 2)

    def test_annotation_data_does_not_enter_word_report(self):
        import tempfile
        from pathlib import Path
        from backend.review_annotations import MARKER
        grading = app.mock_grading(['Essay'])
        annotation = dict(paragraph=1, level='sentence', quote='Essay', kind='good-point', comment='明确表达')
        response = self.response(200, {'output_text': grading.rstrip() + MARKER + json.dumps([annotation])})
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'DATA', Path(directory)), patch('httpx.post', return_value=response):
            folder = Path(directory) / 'annotation-test'
            folder.mkdir()
            saved = [dict(annotation, comment='独立通道的评语')]
            (folder / 'annotations.json').write_text(json.dumps(saved), encoding='utf-8')
            token = app.CURRENT_JOB.set('annotation-test')
            try:
                self.assertEqual(app.call_openai('Essay'), grading)
                self.assertEqual(json.loads((folder / 'annotations.json').read_text(encoding='utf-8'))[0]['kind'], 'good-point')
                self.assertEqual(json.loads((folder / 'annotations.json').read_text(encoding='utf-8'))[0]['level'], 'sentence')
                self.assertEqual(json.loads((folder / 'annotations.json').read_text(encoding='utf-8')), saved)
            finally:
                app.CURRENT_JOB.reset(token)

    def test_annotation_channel_needs_no_paragraph_report(self):
        annotation = dict(paragraph=1, level='sentence', quote='He go.', kind='error',
                          comment='Use goes with the singular subject He.', correction='He goes.')
        with patch('httpx.post', return_value=self.response(200, {'output_text': json.dumps([annotation])})) as post:
            result = app.call_openai('He go.', channel='annotations')
        self.assertEqual(result[0]['correction'], 'He goes.')
        self.assertEqual(post.call_count, 1)

    def test_invalid_annotation_is_repaired_in_its_own_channel(self):
        with patch('httpx.post', side_effect=[
            self.response(200, {'output_text': '[{"quote":"invented"}]'}),
            self.response(200, {'output_text': '[]'}),
        ]) as post:
            self.assertEqual(app.call_openai('Essay', channel='annotations'), [])
        self.assertEqual(post.call_count, 2)

    def test_valid_annotations_survive_one_bad_quote_without_another_ai_call(self):
        items = [dict(paragraph=1,level='phrase',quote='Psychological lecture',kind='error',
                      comment='Add an article before the singular countable noun.',correction='A psychological lecture'),
                 dict(paragraph=1,level='sentence',quote='A psychological lecture can help',
                      kind='error',comment='错误引用',correction='A psychological lecture can help')]
        with patch('httpx.post', return_value=self.response(200, {'output_text':json.dumps(items)})) as post:
            result = app.call_openai('Psychological lecture can help.', channel='annotations')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['quote'], 'Psychological lecture')
        self.assertEqual(post.call_count, 1)

    def test_annotations_survive_failed_report_and_are_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'independent-test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps({'id':'independent-test', 'status':'queued'}), encoding='utf-8')
            (folder / 'source.md').write_text('## Essay\n\nEssay\n', encoding='utf-8')
            with patch.object(app, 'DATA', root), patch.object(app, 'write_source_md', return_value=['Essay']):
                with patch.object(app, 'call_openai', side_effect=[[], RuntimeError('report failed')]):
                    app.run_job('independent-test', None)
                self.assertEqual(json.loads((folder / 'annotations.json').read_text()), [])
                meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
                self.assertEqual(meta['channels'], {'annotations':'ready', 'report':'failed'})
                with patch.object(app, 'call_openai', return_value=app.mock_grading(['Essay'])) as call, patch('backend.app.subprocess.run'):
                    app.run_job('independent-test', None)
                call.assert_called_once_with('## Essay\n\nEssay\n')

    def test_annotation_failure_does_not_block_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'independent-test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps({'id':'independent-test', 'status':'queued'}), encoding='utf-8')
            (folder / 'source.md').write_text('## Essay\n\nEssay\n', encoding='utf-8')
            with patch.object(app, 'DATA', root), patch.object(app, 'write_source_md', return_value=['Essay']), patch.object(app, 'call_openai', side_effect=[RuntimeError('annotations failed'), app.mock_grading(['Essay'])]), patch('backend.app.subprocess.run'):
                app.run_job('independent-test', None)
            meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'], 'succeeded')
            self.assertEqual(meta['channels'], {'annotations':'failed', 'report':'ready', 'translation':'ready'})
            self.assertNotIn('error', meta)
            self.assertTrue((folder / 'grading.md').exists())
            with patch.object(app, 'DATA', root), patch.object(app, 'write_source_md', return_value=['Essay']), patch.object(app, 'call_openai', return_value=[]) as call, patch('backend.app.subprocess.run'):
                app.run_job('independent-test', None)
            call.assert_called_once_with('## Essay\n\nEssay\n', channel='annotations')
            meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'], 'succeeded')
            self.assertNotIn('channel_errors', meta)

    def test_cached_report_with_missing_band_is_regenerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'invalid-cache';folder.mkdir()
            (folder/'meta.json').write_text(json.dumps({'id':'invalid-cache','status':'queued'}),encoding='utf-8')
            (folder/'source.md').write_text('## Essay\n\nEssay\n',encoding='utf-8')
            (folder/'annotations.json').write_text('[]',encoding='utf-8')
            valid=app.mock_grading(['Essay'])
            (folder/'grading.md').write_text(valid.replace('[[red]]4–5[[/red]]','4–5'),encoding='utf-8')
            with patch.object(app,'DATA',root),patch.object(app,'write_source_md',return_value=['Essay']),patch.object(app,'call_openai',return_value=valid) as call,patch('backend.app.subprocess.run'):
                app.run_job('invalid-cache',None)
            call.assert_called_once_with('## Essay\n\nEssay\n')
            app.validate_report((folder/'grading.md').read_text(encoding='utf-8'),['Essay'])

    def test_preview_publishes_annotations_before_report_and_separates_language(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'preview-test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps({'channels': {'annotations':'ready','report':'running'}}), encoding='utf-8')
            (folder / 'source.md').write_text('## Essay\n\nHe go.\n', encoding='utf-8')
            items = [dict(paragraph=1, level='sentence', quote='He go.', kind='error',
                          comment='主谓一致', correction='He goes.')]
            (folder / 'annotations.json').write_text(json.dumps(items), encoding='utf-8')
            with patch.object(app, 'DATA', root), patch.object(app.accounts, 'owned_job', return_value={'filename':'test.docx'}), patch.object(app.accounts, 'audit'):
                preview = app.preview('preview-test', user={'id':'test-user'})
                self.assertEqual(preview['annotations'][0]['correction'], 'He goes.')
                self.assertEqual(preview['review']['paragraphs'], [])
                (folder / 'grading.md').write_text(app.mock_grading(['He go.']), encoding='utf-8')
                updated = app.preview('preview-test', user={'id':'test-user'})
                self.assertEqual(updated['annotations'], preview['annotations'])
                self.assertTrue(updated['language_learning'])
                self.assertEqual(updated['review']['evaluation']['version'], 3)
                self.assertEqual(len(updated['review']['evaluation']['blocks']), 5)
                self.assertEqual(len(updated['review']['evaluation']['blocks'][3]['lexical_sections']), 5)
                self.assertEqual(len(updated['review']['evaluation']['blocks'][4]['grammar_sections']), 5)
                self.assertEqual(len(updated['review']['evaluation']['blocks'][2]['cohesion_sections']), 5)
                self.assertEqual(len(updated['review']['evaluation']['blocks'][1]['task_sections']), 4)
                self.assertEqual(len(updated['review']['evaluation']['blocks'][0]['comprehensive_sections']), 4)
                self.assertNotIn('语言提升', [f['title'] for p in updated['review']['paragraphs'] for f in p['feedback']])

    def test_missing_report_tail_is_repaired(self):
        grading = app.mock_grading(['Essay'])
        incomplete = grading.split('#### 全文综合评价和提升建议')[0]
        with patch('httpx.post', side_effect=[
            self.response(200, {'output_text': incomplete}),
            self.response(200, {'output_text': grading}),
        ]) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_count, 2)

    def test_missing_evaluation_overview_requests_report_repair(self):
        grading = app.mock_grading(['Essay'])
        incomplete = grading.replace('**Task Response｜任务回应**', '**其他点评**')
        with patch('httpx.post', side_effect=[
            self.response(200, {'output_text': incomplete}),
            self.response(200, {'output_text': grading}),
        ]) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(app.report_sections(grading)['evaluation']['version'], 3)

    def test_api_errors_do_not_return_demo(self):
        for response in (self.response(401, {}), self.response(200, {'output': []})):
            with self.subTest(status=response.status_code):
                with patch('httpx.post', return_value=response):
                    with self.assertRaises(RuntimeError):
                        app.call_openai('Essay')

    def test_missing_key_allows_demo_without_request(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch('httpx.post') as post:
            self.assertEqual(app.call_openai('Essay'), '')
            post.assert_not_called()

    def test_gateway_error_is_not_resubmitted(self):
        with patch('httpx.post', return_value=self.response(502, {})) as post:
            with self.assertRaises(RuntimeError):
                app.call_openai('Essay')
        self.assertEqual(post.call_count, 1)

    def test_unmarked_punctuation_is_marked_without_new_generation(self):
        grading = app.mock_grading(['AI-related courses are useful, too.'])
        with patch('httpx.post', return_value=self.response(200, {'output_text': grading})) as post:
            text = app.call_openai('AI related courses are useful too.')
        app.validate_markdown_fidelity(['AI related courses are useful too.'], app.marked_paragraphs(text))
        self.assertIn('{++-++}', text)
        self.assertIn('{++,++}', text)
        self.assertEqual(post.call_count, 1)

    def test_render_failure_hides_internal_command_and_logs_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'render-test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps({'id': 'render-test', 'status': 'queued'}), encoding='utf-8')
            (folder / 'source.md').write_text('## Essay\n\nEssay\n', encoding='utf-8')
            error = subprocess.CalledProcessError(1, ['python', '/private/server/path'], stderr='Reversibility failed')
            with patch.object(app, 'DATA', root), patch.object(app, 'write_source_md', return_value=['Essay']), patch.object(app, 'call_openai', return_value=app.mock_grading(['Essay'])), patch('backend.app.subprocess.run', side_effect=error), self.assertLogs(app.logger, level='ERROR') as logs:
                app.run_job('render-test', None)
            result = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('/private/server/path', result['error'])
            self.assertIn('原始作文已保留', result['error'])
            self.assertIn('exit 1', logs.output[0])
            self.assertNotIn('Reversibility failed', logs.output[0])


if __name__ == '__main__':
    unittest.main()
