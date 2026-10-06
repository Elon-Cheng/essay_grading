import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import app, review_translation
from backend.grading_contract import parse_report, render_report, output_schema
from backend.skill_prompt import build_grading_prompt
from tests.test_grading_contract import report_data


SOURCE = 'We try to discover the cause of the problem.'


def expansion():
    return dict(paragraph=1, original='try to discover', occurrence=1,
                part_of_speech='phr.', meaning_zh='尝试查明',
                synonyms=['attempt to discover', 'seek to uncover', 'aim to identify'])


class SynonymTests(unittest.TestCase):
    def parse(self, items, paragraphs=None):
        source = paragraphs or [SOURCE]
        data = report_data(source)
        data['synonym_expansions'] = items
        return parse_report(json.dumps(data, ensure_ascii=False), source)

    def test_independent_library_preserves_report_score_and_old_cache(self):
        old = parse_report(json.dumps(report_data([SOURCE])), [SOURCE])
        new = self.parse([expansion()])
        self.assertEqual(new.synonym_expansions[0].meaning_zh, '尝试查明')
        self.assertEqual(new.high_score_vocabulary, [])
        self.assertEqual(new.score, old.score)
        self.assertEqual(render_report(new, [SOURCE]), render_report(old, [SOURCE]))
        self.assertEqual(old.model_dump(exclude_unset=True), report_data([SOURCE]))
        self.assertEqual(self.parse([]).synonym_expansions, [])
        self.assertIn('synonym_expansions', output_schema('learning')['required'])

    def test_invalid_source_counts_pos_and_alternatives_rejected(self):
        mutations = [dict(paragraph=2), dict(original='try to explore'), dict(original='cover'),
                     dict(occurrence=2), dict(original=' '), dict(part_of_speech='verb'),
                     dict(meaning_zh='discover'), dict(synonyms=['seek to uncover'] * 3),
                     dict(synonyms=['attempt to discover', 'seek to uncover']),
                     dict(synonyms=['attempt to discover', 'seek to uncover', 'aim to identify', 'a', 'b', 'c']),
                     dict(synonyms=['try to discover', 'seek to uncover', 'aim to identify']),
                     dict(synonyms=[' ', 'seek to uncover', 'aim to identify']),
                     dict(synonyms=['尝试发现', 'seek to uncover', 'aim to identify'])]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.parse([{**expansion(), **mutation}])
        with self.assertRaises(ValueError):
            self.parse([expansion()] * 16)

    def test_complete_phrase_occurrences_and_global_deduplication(self):
        self.assertTrue(self.parse([{**expansion(), 'occurrence': 2}], [SOURCE + ' ' + SOURCE]))
        with self.assertRaisesRegex(ValueError, 'duplicate original'):
            self.parse([expansion(), {**expansion(), 'paragraph': 2}], [SOURCE, SOURCE])

    def test_chinese_meaning_and_english_alternatives_are_not_translated(self):
        preview = {'synonym_expansions': [expansion()]}
        original = copy.deepcopy(preview)
        review_translation.validate_english_feedback(preview)
        for language in ('en', 'zh'):
            self.assertEqual(review_translation.translation_texts(preview, language), [])
            rendered = review_translation.apply_translation(preview, {'尝试查明': 'Changed'}, language)
            self.assertEqual(rendered['synonym_expansions'], original['synonym_expansions'])
        self.assertEqual(preview, original)

    def test_preview_reads_library_and_legacy_reports_need_no_regeneration(self):
        report = self.parse([expansion()])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'synonym-job'
            folder.mkdir()
            (folder / 'source.md').write_text('## Essay\n\n' + SOURCE + '\n', encoding='utf-8')
            (folder / 'grading.md').write_text(render_report(report, [SOURCE]), encoding='utf-8')
            app.write_meta(folder / 'meta.json', {'status': 'succeeded'})
            app.write_meta(folder / 'report.json', report.model_dump())
            with patch.object(app, 'DATA', root), patch.object(app.accounts, 'owned_job', return_value={'filename': 'test.docx'}), patch.object(app.accounts, 'audit'):
                preview = app.preview(folder.name, user={'id': 1})
                self.assertEqual(preview['synonym_expansions'], [expansion()])
                (folder / 'report.json').unlink()
                legacy = app.preview(folder.name, user={'id': 1})
                self.assertNotIn('synonym_expansions', legacy)
                self.assertEqual(preview['grading'], legacy['grading'])
            app.write_meta(folder / 'report.json', {'synonym_expansions': [{**expansion(), 'paragraph': 2}]})
            self.assertEqual(app.saved_synonyms(folder, [SOURCE]), [])

    def test_skill_only_loaded_into_report_channel(self):
        root = app.ROOT / 'backend'
        self.assertIn('# 近义词拓展', build_grading_prompt(root, 'learning'))
        self.assertNotIn('# 近义词拓展', build_grading_prompt(root, 'annotations'))


if __name__ == '__main__':
    unittest.main()
