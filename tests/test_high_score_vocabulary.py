import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx

from backend import app, review_translation
from backend.grading_contract import parse_report, render_report, output_schema
from backend.skill_prompt import build_grading_prompt
from tests.test_grading_contract import report_data


SOURCE = 'More and more people try to discover various destinations.'


def upgrade():
    return dict(paragraph=1, source_sentence=SOURCE, sentence_occurrence=1,
                original='discover', replacement='explore', word_occurrence=1,
                minimal_sentence=SOURCE.replace('discover', 'explore'),
                example_sentence='Travellers can explore coastal towns and learn about local food traditions.',
                reason='The writer means visiting and learning about places, rather than finding unknown destinations. Explore expresses active engagement more precisely.',
                collocations=['explore possibilities', 'explore a concept', 'explore options'])


class VocabularyTests(unittest.TestCase):
    def parse(self, items, source=SOURCE):
        data = report_data([source])
        data['high_score_vocabulary'] = items
        return parse_report(json.dumps(data), [source])

    def test_structured_learning_chain_preserves_existing_report_and_score(self):
        old = parse_report(json.dumps(report_data([SOURCE])), [SOURCE])
        new = self.parse([upgrade()])
        self.assertEqual(new.high_score_vocabulary[0].replacement, 'explore')
        self.assertEqual(new.score, old.score)
        self.assertEqual(render_report(new, [SOURCE]), render_report(old, [SOURCE]))
        self.assertIn('high_score_vocabulary', output_schema('learning')['required'])
        self.assertEqual(old.high_score_vocabulary, [])
        self.assertEqual(old.model_dump(exclude_unset=True), report_data([SOURCE]))
        self.assertEqual(self.parse([]).high_score_vocabulary, [])

    def test_fabricated_quotes_extra_edits_bad_examples_and_collocations_rejected(self):
        mutations = [dict(paragraph=2), dict(source_sentence='Invented sentence.'),
                     dict(sentence_occurrence=2), dict(original='cover'), dict(word_occurrence=2),
                     dict(replacement='discover'), dict(minimal_sentence='People explore destinations.'),
                     dict(example_sentence=upgrade()['minimal_sentence']),
                     dict(example_sentence='Travellers visit towns.'), dict(reason=' '),
                     dict(reason='这个词更高级'), dict(collocations=['explore options']),
                     dict(collocations=['explore options', 'explore options']),
                     dict(collocations=['explore options', 'visit towns'])]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.parse([{**upgrade(), **mutation}])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.parse([upgrade(), upgrade()])

    def test_repeated_target_changes_only_requested_occurrence(self):
        source = 'We discover towns and discover local cultures.'
        item = {**upgrade(), 'source_sentence': source, 'word_occurrence': 2,
                'minimal_sentence': 'We discover towns and explore local cultures.'}
        self.assertEqual(self.parse([item], source).high_score_vocabulary[0].word_occurrence, 2)

    def test_repair_diagnostics_include_errors_in_multiple_independent_modules(self):
        data = report_data([SOURCE])
        data['high_score_vocabulary'] = [{**upgrade(), 'sentence_occurrence': 2}]
        data['topic_collocations'] = dict(topic='Travel', items=[dict(
            phrase='explore different cultures', example_sentence='Travellers visit towns.',
            origin='supplement', paragraph=0, occurrence=0)])
        with self.assertRaises(ValueError) as raised:
            parse_report(json.dumps(data), [SOURCE])
        error = str(raised.exception)
        self.assertIn('exact sentence occurs 1 time(s)', error)
        self.assertIn('topic_collocations', error)
        self.assertIn('explore different cultures', error)

    def test_inflected_single_word_allows_base_form_collocations_but_phrases_stay_complete(self):
        source = 'Our club boasts creative designs.'
        item = {**upgrade(), 'source_sentence': source, 'original': 'boasts', 'replacement': 'showcases',
                'minimal_sentence': 'Our club showcases creative designs.',
                'example_sentence': 'The exhibition showcases original designs by students.',
                'collocations': ['showcase creativity', 'showcase original designs']}
        self.assertTrue(self.parse([item], source).high_score_vocabulary)
        source = 'I have a strong willingness to learn.'
        item.update(source_sentence=source, original='strong willingness', replacement='strong desire',
                    minimal_sentence='I have a strong desire to learn.',
                    example_sentence='Students can express a strong desire to learn about their culture.',
                    collocations=['a strong desire to', 'express a desire to'])
        with self.assertRaisesRegex(ValueError, 'complete phrase'):
            self.parse([item], source)

    def test_prepared_translation_changes_reason_only(self):
        preview = {'high_score_vocabulary': [upgrade()]}
        reason = upgrade()['reason']
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(review_translation, 'translate_texts', return_value={reason: '这里强调主动探访，explore 更准确。'}) as translate:
                maps = review_translation.prepare_translations(folder, preview, 'test-job')
            translate.assert_called_once_with([reason], 'zh', 'test-job')
            self.assertTrue((folder / 'prepared-zh.json').exists())
            chinese = review_translation.apply_translation(preview, maps['zh'], 'zh')
            expected = copy.deepcopy(preview)
            expected['high_score_vocabulary'][0]['reason'] = maps['zh'][reason]
            expected['display_language'] = 'zh'
            self.assertEqual(chinese, expected)
            self.assertEqual(preview['high_score_vocabulary'][0], upgrade())

    def test_preview_reads_cached_data_and_old_jobs_need_no_regeneration(self):
        report = self.parse([upgrade()])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'test-job'
            folder.mkdir()
            (folder / 'source.md').write_text('## Essay\n\n' + SOURCE + '\n', encoding='utf-8')
            (folder / 'grading.md').write_text(render_report(report, [SOURCE]), encoding='utf-8')
            app.write_meta(folder / 'meta.json', {'status': 'succeeded'})
            app.write_meta(folder / 'report.json', report.model_dump())
            with patch.object(app, 'DATA', root), patch.object(app.accounts, 'owned_job', return_value={'filename': 'test.docx'}), patch.object(app.accounts, 'audit'):
                preview = app.preview(folder.name, user={'id': 1})
                self.assertEqual(preview['high_score_vocabulary'], [upgrade()])
                (folder / 'report.json').unlink()
                legacy = app.preview(folder.name, user={'id': 1})
                self.assertNotIn('high_score_vocabulary', legacy)
                self.assertEqual(preview['grading'], legacy['grading'])
            # Invalid cached targets are not served even if legacy Markdown exists.
            app.write_meta(folder / 'report.json', {'high_score_vocabulary': [{**upgrade(), 'paragraph': 20}]})
            self.assertEqual(app.saved_vocabulary(folder, [SOURCE]), [])

    def test_worker_persists_vocabulary_renders_word_and_reuses_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'vocabulary-job'
            folder.mkdir()
            fixture = next((app.ROOT / 'tests' / 'cases').glob('*.docx'))
            with ZipFile(fixture) as original, ZipFile(folder / 'source.docx', 'w') as output:
                for info in original.infolist():
                    content = original.read(info.filename)
                    if info.filename == 'word/document.xml':
                        tree = ET.fromstring(content)
                        body = tree.find('w:body', app.NS)
                        for child in list(body):
                            if child.tag != '{' + app.W + '}sectPr':
                                body.remove(child)
                        paragraph = ET.Element('{' + app.W + '}p')
                        text = ET.SubElement(ET.SubElement(paragraph, '{' + app.W + '}r'), '{' + app.W + '}t')
                        text.text = SOURCE
                        body.insert(0, paragraph)
                        content = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
                    output.writestr(info, content)
            data = report_data([SOURCE])
            data['high_score_vocabulary'] = [upgrade()]
            synonyms = dict(paragraph=1, original='try to discover', occurrence=1,
                            part_of_speech='phr.', meaning_zh='尝试发现',
                            synonyms=['attempt to discover', 'seek to discover', 'aim to discover'])
            data['synonym_expansions'] = [synonyms]
            topic = dict(topic='Travel & Exploration', items=[dict(
                phrase='explore different cultures',
                example_sentence='Travellers can explore different cultures at local festivals.',
                origin='supplement', paragraph=0, occurrence=0)])
            data['topic_collocations'] = topic
            responses = [httpx.Response(200, json={'status': 'completed', 'output_text': json.dumps(value)},
                                       request=httpx.Request('POST', 'https://example.com/v1/responses'))
                         for value in ({'annotations': []}, data)]
            app.write_meta(folder / 'meta.json', {'id': folder.name, 'status': 'queued'})
            with patch.object(app, 'DATA', root), patch.object(app.accounts, 'DB', root / 'test.sqlite3'), \
                    patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'AI_STREAM': '0', 'AI_STRUCTURED_OUTPUT': '1', 'AI_LEARNING_ENABLED': '0'}), \
                    patch.object(app.review_translation, 'prepare_translations', return_value={}) as prepare:
                app.accounts.initialize()
                with patch('backend.ai_transport.request_response', side_effect=responses) as request:
                    app.run_job(folder.name, None)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(app.read_meta(folder / 'meta.json')['status'], 'succeeded')
                self.assertEqual(app.read_meta(folder / 'report.json')['high_score_vocabulary'], [upgrade()])
                self.assertEqual(app.read_meta(folder / 'report.json')['synonym_expansions'], [synonyms])
                self.assertEqual(app.read_meta(folder / 'report.json')['topic_collocations'], topic)
                self.assertEqual(prepare.call_args.args[1]['high_score_vocabulary'], [upgrade()])
                self.assertTrue((folder / 'graded.docx').exists())
                grading = (folder / 'grading.md').read_bytes()
                with patch('backend.ai_transport.request_response') as request:
                    app.run_job(folder.name, None)
                request.assert_not_called()
                self.assertEqual((folder / 'grading.md').read_bytes(), grading)

    def test_skill_loaded_by_report_channel_only(self):
        root = app.ROOT / 'backend'
        report = build_grading_prompt(root, 'learning')
        self.assertIn('# 高分词识别与提升', report)
        self.assertNotIn('# 高分词识别与提升', build_grading_prompt(root, 'annotations'))


if __name__ == '__main__':
    unittest.main()
