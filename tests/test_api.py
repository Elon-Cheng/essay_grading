import os
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import app


class GradingApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.dict(os.environ, {
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_BASE_URL': 'https://www.su8.codes/v1/',
            'OPENAI_MODEL': 'gpt-5.5',
        })
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def response(self, status, body):
        return httpx.Response(status, json=body, request=httpx.Request(
            'POST', 'https://www.su8.codes/v1/responses'))

    def test_configured_endpoint_and_output(self):
        grading = app.mock_grading(['Essay'])
        response = self.response(200, {'output': [{'content': [
            {'type': 'output_text', 'text': grading}]}]})
        with patch('httpx.post', return_value=response) as post:
            self.assertEqual(app.call_openai('Essay'), grading)
        self.assertEqual(post.call_args.args[0], 'https://www.su8.codes/v1/responses')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(post.call_args.kwargs['json']['model'], 'gpt-5.5')

    def test_invalid_format_is_repaired_before_returning(self):
        grading = app.mock_grading(['Essay'])
        with patch('httpx.post', side_effect=[
            self.response(200, {'output_text': '**段落点评：** 缺少原文'}),
            self.response(200, {'output_text': grading}),
        ]) as post:
            self.assertEqual(app.call_openai('## Essay\n\nEssay\n'), grading)
        self.assertEqual(post.call_count, 2)

    def test_unmarked_rewrite_is_never_accepted(self):
        grading = app.mock_grading(['A changed sentence.'])
        with patch('httpx.post', return_value=self.response(200, {'output_text': grading})) as post:
            with self.assertRaisesRegex(RuntimeError, '原始作文已保留'):
                app.call_openai('## Essay\n\nAn original sentence.\n')
        self.assertEqual(post.call_count, 2)

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

    def test_render_failure_hides_internal_command_and_logs_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'render-test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps({'id': 'render-test', 'status': 'queued'}), encoding='utf-8')
            (folder / 'source.md').write_text('## Essay\n\nEssay\n', encoding='utf-8')
            error = subprocess.CalledProcessError(1, ['python', '/private/server/path'], stderr='Reversibility failed')
            with patch.object(app, 'DATA', root), patch.object(app, 'write_source_md', return_value=['Essay']), patch.object(app, 'call_openai', return_value='grading'), patch('app.subprocess.run', side_effect=error), self.assertLogs(app.logger, level='ERROR') as logs:
                app.run_job('render-test', None)
            result = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('/private/server/path', result['error'])
            self.assertIn('原始作文已保留', result['error'])
            self.assertIn('Reversibility failed', logs.output[0])


if __name__ == '__main__':
    unittest.main()
