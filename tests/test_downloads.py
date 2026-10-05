import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from fastapi.testclient import TestClient
import app
import accounts


class CompleteReportTests(unittest.TestCase):
    def test_missing_sections_are_rejected(self):
        report = app.mock_grading(['An original sentence.'])
        app.validate_complete_report(report)
        for incomplete in (
            report.split('#### 全文综合评价和提升建议')[0],
            report.replace('#### 语言提升', '#### 其他'),
            report.replace('本篇文章打分估计为：18—21分。', ''),
            report.replace('| E | 0–2 | 0–2 | 0 |', ''),
            report.replace('18—21分', '26分'),
        ):
            with self.subTest(report=incomplete), self.assertRaises(ValueError):
                app.validate_complete_report(incomplete)

    def test_download_content_filename_and_incomplete_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(app, 'DATA', root), patch.object(accounts, 'DB', root/'accounts.sqlite3'):
                accounts.initialize()
                with TestClient(app.app) as client:
                    client.post('/api/auth/register', json={'username':'download_test', 'password':'password-12345'})
                    fixture = next((app.ROOT/'tests'/'cases').glob('*.docx'))
                    with patch.object(app, 'call_openai', return_value=''):
                        created = client.post('/api/essays', files={'file':('学生作文.docx', fixture.read_bytes())})
                    job = created.json()['id']
                    folder = root/job
                    self.assertEqual(app.read_meta(folder/'meta.json')['status'], 'succeeded')
                    response = client.get(f'/api/essays/{job}/download')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('学生作文-完整批改报告.docx', unquote(response.headers['content-disposition']))
                    self.assertEqual(int(response.headers['content-length']), len(response.content))
                    self.assertEqual(response.content, (folder/'graded.docx').read_bytes())
                    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                        self.assertIsNone(archive.testzip())
                        xml = archive.read('word/document.xml').decode('utf-8')
                        for text in ('段落点评', '语言提升', '问题建议', '全文综合评价和提升建议', '本篇文章打分估计为'):
                            self.assertIn(text, xml)
                    self.assertEqual((folder/'source.docx').read_bytes(), fixture.read_bytes())
                    preview = client.get(f'/api/essays/{job}/preview').json()
                    self.assertEqual(preview['original'], app.source_paragraphs(preview['source']))
                    self.assertEqual(len(preview['review']['paragraphs']), len(preview['original']))
                    self.assertTrue(preview['review']['overall'])
                    self.assertEqual(preview['annotations'], [])
                    self.assertIn('prompt', preview)
                    quote = preview['original'][0][:3]
                    (folder/'annotations.json').write_text(json.dumps([dict(paragraph=1,quote=quote,
                        start=0,kind='good-point',comment='具体表达优点')]), encoding='utf-8')
                    annotated = client.get(f'/api/essays/{job}/preview').json()
                    self.assertEqual(annotated['annotations'][0]['quote'], quote)
                    self.assertEqual(annotated['grading'], preview['grading'])
                    meta = app.read_meta(folder/'meta.json')
                    for state in ('queued', 'running', 'failed'):
                        meta['status'] = state
                        app.write_meta(folder/'meta.json', meta)
                        with accounts.database() as db:
                            db.execute('UPDATE jobs SET status=? WHERE id=?', (state, job))
                        self.assertEqual(client.get(f'/api/essays/{job}/download').status_code, 409)
                    meta['status'] = 'succeeded'
                    app.write_meta(folder/'meta.json', meta)
                    with accounts.database() as db:
                        db.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (job,))
                    (folder/'graded.docx').write_bytes(b'incomplete zip')
                    with self.assertLogs(app.logger, level='ERROR'):
                        self.assertEqual(client.get(f'/api/essays/{job}/download').status_code, 409)
                    (folder/'graded.docx').unlink()
                    self.assertEqual(client.get(f'/api/essays/{job}/download').status_code, 404)
