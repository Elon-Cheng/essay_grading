import json
import tempfile
import unittest
from pathlib import Path

from scripts.recover_saved_annotations import recover


class AnnotationRecoveryTests(unittest.TestCase):
    def test_recovery_uses_saved_response_and_preserves_delivered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ident = 'a' * 32
            folder = root / 'data' / ident
            rejected = folder / 'ai-rejected'
            rejected.mkdir(parents=True)
            protected = {'source.md':b'## Essay\n\nPsychological lecture can help.\n',
                         'source.docx':b'original document', 'grading.md':b'delivered report',
                         'graded.docx':b'delivered word'}
            for name, data in protected.items():
                (folder / name).write_bytes(data)
            meta = {'status':'succeeded','channels':{'annotations':'failed','report':'ready'}}
            (folder / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
            items = [dict(paragraph=1,level='phrase',quote='Psychological lecture',kind='error',
                          comment='缺少冠词',correction='A psychological lecture'),
                     dict(paragraph=1,level='phrase',quote='A psychological lecture',kind='error',
                          comment='引用改写',correction='A psychological lecture')]
            (rejected / 'saved.md').write_text(json.dumps(items), encoding='utf-8')
            plan = recover(root, ident)
            self.assertEqual((plan['kept'],plan['discarded']), (1,1))
            self.assertFalse((folder / 'annotations.json').exists())
            result = recover(root, ident, apply=True)
            self.assertTrue(result['original_and_report_unchanged'])
            self.assertEqual(json.loads((folder / 'meta.json').read_text())['channels']['annotations'], 'ready')
            self.assertEqual(len(json.loads((folder / 'annotations.json').read_text(encoding='utf-8'))), 1)
            self.assertEqual(json.loads((Path(result['backup']) / 'meta.json').read_text()), meta)
            for name, data in protected.items():
                self.assertEqual((folder / name).read_bytes(), data)
            with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                recover(root, ident, apply=True)
