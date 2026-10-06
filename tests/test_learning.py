import json
import os
import tempfile
import unittest
import httpx
from pathlib import Path
from unittest.mock import patch

from backend import app, accounts
from backend.learning import parse_learning
from backend.grading_contract import output_schema, render_report, parse_report
from tests.test_high_score_vocabulary import upgrade, SOURCE
from tests.test_grading_contract import report_data


def bilingual_data():
    return {'high_score_vocabulary': [{**upgrade(),
        'original_zh': '发现', 'replacement_zh': '探索',
        'source_sentence_zh': '越来越多的人尝试发现各种目的地。',
        'minimal_sentence_zh': '越来越多的人尝试探索各种目的地。',
        'example_sentence_zh': '旅行者可以探索沿海城镇，了解当地饮食传统。',
        'reason_zh': '原句指主动游览和了解地点，explore 比强调发现未知事物的 discover 更精准。',
        'collocations_zh': ['探索可能性', '探讨一个概念', '探索各种选择']}],
        'synonym_expansions': [{'paragraph': 1, 'original': 'try to discover', 'occurrence': 1,
            'part_of_speech': 'phr.', 'meaning_zh': '尝试发现', 'meaning_en': 'make an effort to discover',
            'synonyms': ['attempt to discover', 'seek to discover', 'aim to discover'],
            'synonyms_zh': ['尝试发现', '力求发现', '旨在发现']}],
        'topic_collocations': {'topic': 'Travel & Exploration', 'topic_zh': '旅行与探索', 'items': [
            {'phrase': 'various destinations', 'phrase_zh': '各种目的地',
             'example_sentence': 'Travellers visit various destinations to learn about local cultures.',
             'example_sentence_zh': '旅行者前往各种目的地，了解当地文化。',
             'origin': 'source', 'paragraph': 1, 'occurrence': 1}]}}


class LearningTests(unittest.TestCase):
    def test_structured_api_filters_invalid_card_without_repeating_generation(self):
        candidate = bilingual_data()
        candidate['topic_collocations']['items'].append({
            **candidate['topic_collocations']['items'][0], 'phrase': 'invented expression'})
        response = httpx.Response(200, json={'output_text': json.dumps(candidate)},
                                  request=httpx.Request('POST', 'https://example.com/v1/responses'))
        with patch.dict(os.environ, {'OPENAI_API_KEY':'test','AI_STRUCTURED_OUTPUT':'1'}), \
                patch('backend.ai_transport.request_response', return_value=response) as request, \
                patch.object(app.saas, 'start_call', return_value='learning-test'), \
                patch.object(app.saas, 'finish_call'):
            data, errors = app.call_openai(SOURCE, channel='learning')
        request.assert_called_once()
        body = request.call_args.args[2]
        self.assertEqual(body['text']['format']['name'], 'essay_learning')
        self.assertNotIn('score', body['text']['format']['schema']['properties'])
        self.assertEqual(len(data['topic_collocations']['items']), 1)
        self.assertTrue(errors)
        self.assertEqual(data['high_score_vocabulary'], bilingual_data()['high_score_vocabulary'])

    def test_three_bilingual_modules_and_core_schema_isolation(self):
        expected = bilingual_data()
        data, errors = parse_learning(json.dumps(expected), [SOURCE])
        self.assertEqual(data, expected)
        self.assertEqual(errors, [])
        self.assertNotIn('high_score_vocabulary', output_schema('report')['properties'])
        self.assertIn('high_score_vocabulary', output_schema('learning')['required'])

    def test_invalid_card_does_not_hide_valid_other_modules(self):
        data = bilingual_data()
        data['high_score_vocabulary'][0]['example_sentence_zh'] = 'Not Chinese'
        result, errors = parse_learning(json.dumps(data), [SOURCE])
        self.assertEqual(result['high_score_vocabulary'], [])
        self.assertTrue(result['synonym_expansions'])
        self.assertTrue(result['topic_collocations']['items'])
        self.assertTrue(errors)
        data = bilingual_data()
        data['synonym_expansions'][0]['synonyms_zh'].pop()
        result, errors = parse_learning(json.dumps(data), [SOURCE])
        self.assertEqual(result['synonym_expansions'], [])
        self.assertTrue(result['high_score_vocabulary'])

    def test_failed_learning_keeps_word_and_score_then_success_and_cache(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'independent-learning'
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
            app.write_meta(folder / 'meta.json', {'id': folder.name, 'status': 'queued'})
            grading = render_report(parse_report(json.dumps(report_data([SOURCE])), [SOURCE]), [SOURCE])
            def generate(source, channel='report'):
                if channel == 'annotations':
                    return []
                if channel == 'report':
                    return grading
                raise RuntimeError('Synthetic upstream outage')
            with patch.object(app, 'DATA', root), patch.object(accounts, 'DB', root / 'test.sqlite3'), \
                    patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'AI_LEARNING_ENABLED': '1'}), \
                    patch.object(app.review_translation, 'prepare_translations', return_value={}):
                accounts.initialize()
                with patch.object(app, 'call_openai', side_effect=generate):
                    app.run_job(folder.name, None)
                meta = app.read_meta(folder / 'meta.json')
                self.assertEqual(meta['status'], 'succeeded', meta.get('error'))
                self.assertEqual(meta['channels']['learning'], 'failed')
                self.assertTrue((folder / 'graded.docx').exists())
                with patch.object(app, 'call_openai', return_value=(bilingual_data(), [])) as request:
                    app.run_job(folder.name, None)
                request.assert_called_once()
                self.assertEqual(app.read_meta(folder / 'meta.json')['channels']['learning'], 'ready')
                with patch.object(app.accounts, 'owned_job', return_value={'filename': 'test.docx'}):
                    preview = app.preview(folder.name, user={'id': 1})
                self.assertEqual(preview['high_score_vocabulary'][0]['reason_zh'], bilingual_data()['high_score_vocabulary'][0]['reason_zh'])
                with patch.object(app, 'call_openai') as request:
                    app.run_job(folder.name, None)
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
