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


SOURCE = 'We travel to new places to learn about local traditions.'


def library():
    return dict(topic='Travel & Exploration', items=[
        dict(phrase='travel to new places', example_sentence='Families often travel to new places during the holidays.',
             origin='source', paragraph=1, occurrence=1),
        dict(phrase='experience different cultures', example_sentence='Visitors can experience different cultures through local festivals.',
             origin='supplement', paragraph=0, occurrence=0)])


class TopicCollocationTests(unittest.TestCase):
    def parse(self, value, paragraphs=None):
        source = paragraphs or [SOURCE]
        data = report_data(source)
        data['topic_collocations'] = value
        return parse_report(json.dumps(data), source)

    def test_library_is_independent_and_leaves_report_score_and_old_cache_intact(self):
        old = parse_report(json.dumps(report_data([SOURCE])), [SOURCE])
        new = self.parse(library())
        self.assertEqual(new.topic_collocations.model_dump(), library())
        self.assertEqual(new.high_score_vocabulary, [])
        self.assertEqual(new.synonym_expansions, [])
        self.assertEqual(new.score, old.score)
        self.assertEqual(render_report(new, [SOURCE]), render_report(old, [SOURCE]))
        self.assertEqual(old.model_dump(exclude_unset=True), report_data([SOURCE]))
        self.assertIsNone(self.parse(None).topic_collocations)
        self.assertEqual(self.parse({'topic': 'Travel', 'items': []}).topic_collocations.items, [])
        self.assertIn('topic_collocations', output_schema('learning')['required'])

    def test_invalid_phrases_examples_source_claims_and_counts_rejected(self):
        mutations = [dict(phrase='travel'), dict(phrase=' travel to new places'),
                     dict(phrase='visit new places'), dict(paragraph=2), dict(paragraph=0),
                     dict(occurrence=0), dict(occurrence=2), dict(origin='unknown'),
                     dict(example_sentence='Families visit towns.'),
                     dict(example_sentence='Families travel to new placesx.'),
                     dict(example_sentence='游客 travel to new places。')]
        for mutation in mutations:
            value = library()
            value['items'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.parse(value)
        for paragraph, occurrence in ((1, 0), (0, 1)):
            value = library()
            value['items'][1].update(paragraph=paragraph, occurrence=occurrence)
            with self.assertRaisesRegex(ValueError, 'must not claim'):
                self.parse(value)
        for value in ({'topic': ' ', 'items': []}, {'topic': 'Travel', 'items': library()['items'] * 6}):
            with self.assertRaises(ValueError):
                self.parse(value)

    def test_occurrence_and_deduplication_with_example_capitalization(self):
        value = library()
        value['items'][0].update(occurrence=2, example_sentence='Travel to new places with friends during the holidays.')
        self.assertTrue(self.parse(value, [SOURCE + ' ' + SOURCE]).topic_collocations)
        value['items'].append(copy.deepcopy(value['items'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate phrases'):
            self.parse(value, [SOURCE + ' ' + SOURCE])

    def test_example_sentences_remain_english_during_feedback_translation(self):
        preview = {'topic_collocations': library()}
        for language in ('en', 'zh'):
            self.assertEqual(review_translation.translation_texts(preview, language), [])
            translated = review_translation.apply_translation(preview, {}, language)
            self.assertEqual(translated['topic_collocations'], library())

    def test_preview_serves_saved_library_and_skips_old_or_invalid_data(self):
        report = self.parse(library())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'topic-job'
            folder.mkdir()
            (folder / 'source.md').write_text('## Essay\n\n' + SOURCE + '\n', encoding='utf-8')
            (folder / 'grading.md').write_text(render_report(report, [SOURCE]), encoding='utf-8')
            app.write_meta(folder / 'meta.json', {'status': 'succeeded'})
            app.write_meta(folder / 'report.json', report.model_dump())
            with patch.object(app, 'DATA', root), patch.object(app.accounts, 'owned_job', return_value={'filename': 'test.docx'}), patch.object(app.accounts, 'audit'):
                preview = app.preview(folder.name, user={'id': 1})
                self.assertEqual(preview['topic_collocations'], library())
                (folder / 'report.json').unlink()
                legacy = app.preview(folder.name, user={'id': 1})
                self.assertNotIn('topic_collocations', legacy)
                self.assertEqual(legacy['grading'], preview['grading'])
            invalid = library()
            invalid['items'][0]['paragraph'] = 3
            app.write_meta(folder / 'report.json', {'topic_collocations': invalid})
            self.assertIsNone(app.saved_topic_collocations(folder, [SOURCE]))

    def test_skill_loaded_only_for_report(self):
        root = app.ROOT / 'backend'
        self.assertIn('# 话题词伙', build_grading_prompt(root, 'learning'))
        self.assertNotIn('# 话题词伙', build_grading_prompt(root, 'annotations'))


if __name__ == '__main__':
    unittest.main()
