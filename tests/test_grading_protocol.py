import unittest
from grading_protocol import repair_paragraph
from scripts.render_grading_docx import recover_original, validate_markdown_fidelity


class ProtocolTests(unittest.TestCase):
    def test_existing_word_edits_and_unmarked_punctuation(self):
        source = 'AI related courses can help. They can help too.'
        marked = 'AI-related courses ~~can~~{++will++} help. They can help, too.'
        fixed = repair_paragraph(source, marked)
        self.assertEqual(recover_original(fixed), source)
        validate_markdown_fidelity([source], [fixed])
        self.assertIn('~~can~~{++will++}', fixed)
        self.assertIn('{++,++}', fixed)

    def test_unmarked_word_rewrite_is_not_repaired(self):
        source = 'He goes to school.'
        marked = 'He went to school.'
        self.assertEqual(repair_paragraph(source, marked), marked)
        with self.assertRaises(ValueError):
            validate_markdown_fidelity([source], [marked])

    def test_punctuation_inside_deleted_target_is_not_reinterpreted(self):
        marked = '~~AI-related~~{++AI courses++} are useful.'
        self.assertEqual(repair_paragraph('AI related are useful.', marked), marked)
