"""Verify the physical split preserves public resources and entry points."""
import importlib
import unittest
from fastapi.testclient import TestClient
from backend import app, worker


class ProjectStructureTests(unittest.TestCase):
    def test_legacy_entry_points_share_backend_state(self):
        self.assertIs(importlib.import_module('app'), app)
        self.assertIs(importlib.import_module('worker'), worker)

    def test_all_frontend_files_keep_their_static_urls(self):
        with TestClient(app.app) as client:
            for file in (app.ROOT / 'frontend').iterdir():
                if file.is_file():
                    with self.subTest(file=file.name):
                        response = client.get('/static/' + file.name)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.content, file.read_bytes())

    def test_word_renderer_import_has_no_web_application_dependency(self):
        from backend import documents
        self.assertEqual(documents.source_paragraphs('## Essay\n\nOriginal sentence.'), ['Original sentence.'])
        self.assertNotIn('fastapi', documents.__dict__)
