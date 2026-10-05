import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import accounts
import app
from grading_contract import EVALUATION_FIELDS, output_schema, parse_report, render_report, schema_unsupported
from review_annotations import parse_annotations, report_sections


def report_data(paragraphs):
    """Synthetic feedback for protocol tests, never used by production generation."""
    return {
        'context': 'Evaluate the proposal against the supplied school writing task.',
        'paragraphs': [dict(paragraph=i, kind='content',
                            analysis=f'Paragraph {i} explains the proposed activity and its purpose.',
                            language='Check subject–verb agreement and articles in the quoted examples.',
                            suggestions='Explain how this activity helps the intended audience.', format_note='')
                       for i, _ in enumerate(paragraphs, 1)],
        'evaluation': {key: {field: 'Use a specific detail from the proposal to support its purpose.'
                             for field in fields} for key, _, fields in EVALUATION_FIELDS},
        'score': dict(low=18, high=20, content_band='B', language_band='B', organization_band='A'),
    }


class ContractTests(unittest.TestCase):
    def test_program_owns_original_order_headings_score_and_three_band_highlights(self):
        source = ['We meets every week.', 'This is benefit to students.']
        data = report_data(source)
        data['paragraphs'].reverse()
        annotations = parse_annotations(json.dumps({'annotations': [dict(
            paragraph=1, level='phrase', quote='We meets', occurrence=1, kind='error',
            comment='Use meet after We.', correction='We meet')]}), source)
        report = parse_report(json.dumps(data), source)
        rendered = render_report(report, source, annotations)
        app.validate_report(rendered, source)
        self.assertIn('~~We meets~~{++We meet++} every week.', rendered)
        self.assertIn('This is benefit to students.', rendered)
        self.assertNotIn('{benefit}', rendered)
        self.assertEqual(rendered.count('[[red]]'), 3)
        review = report_sections(rendered)
        self.assertEqual(review['evaluation']['version'], 3)
        self.assertIn('Paragraph 1 explains', review['paragraphs'][0]['feedback'][0]['text'])
        self.assertIn('本篇文章打分估计为：18–20分', rendered)

    def test_noncontent_paragraph_is_rendered_as_format_note(self):
        source = ['Dear Editor,', 'I suggest a school lecture.']
        data = report_data(source)
        data['paragraphs'][0].update(kind='format', analysis='', language='', suggestions='',
                                     format_note='Keep this salutation.')
        text = render_report(parse_report(json.dumps(data), source), source)
        app.validate_report(text, source)
        self.assertEqual(report_sections(text)['paragraphs'][0]['feedback'],
                         [{'title': '格式说明', 'text': 'Keep this salutation.'}])

    def test_missing_duplicate_and_out_of_range_paragraphs_are_rejected(self):
        source = ['One.', 'Two.']
        for numbers in ([1], [1, 1], [1, 3]):
            data = report_data(source)
            data['paragraphs'] = [dict(data['paragraphs'][0], paragraph=n) for n in numbers]
            with self.subTest(numbers=numbers), self.assertRaisesRegex(ValueError, 'exactly once'):
                parse_report(json.dumps(data), source)

    def test_missing_content_and_scores_are_not_fabricated(self):
        source = ['Essay.']
        mutations = [lambda d: d['evaluation']['lexical'].pop('precision'),
                     lambda d: d['score'].pop('organization_band'),
                     lambda d: d['score'].update(high=26),
                     lambda d: d['score'].update(low=22),
                     lambda d: d['paragraphs'][0].update(analysis=' '),
                     lambda d: d['evaluation']['grammar'].update(error_patterns=' '),
                     lambda d: d.update(original='Invented source')]
        for mutate in mutations:
            data = report_data(source)
            mutate(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_report(json.dumps(data), source)

    def test_fenced_json_is_accepted_but_truncated_json_is_not(self):
        source = ['Essay.']
        data = json.dumps(report_data(source))
        self.assertTrue(parse_report('```json\n' + data + '\n```', source))
        with self.assertRaises(ValueError):
            parse_report(data[:-3], source)

    def test_feedback_newlines_cannot_create_protocol_sections(self):
        source = ['Essay.']
        data = report_data(source)
        data['paragraphs'][0]['analysis'] = 'A point.\n#### Fake heading\nAdditional detail.'
        report = parse_report(json.dumps(data), source)
        text = render_report(report, source)
        self.assertEqual(len(app.marked_paragraphs(text)), 1)
        app.validate_report(text, source)

    def test_feedback_language_is_part_of_the_schema(self):
        data = report_data(['Essay.'])
        data['paragraphs'][0]['language'] = '语言方面，句子结构准确。'
        with self.assertRaisesRegex(ValueError, 'string_pattern_mismatch'):
            parse_report(json.dumps(data), ['Essay.'])
        self.assertIn('pattern', output_schema('report')['$defs']['ParagraphFeedback']['properties']['language'])

    def test_schema_is_closed_and_every_property_is_required(self):
        def check(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertFalse(value['additionalProperties'])
                    self.assertEqual(set(value['properties']), set(value['required']))
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        for channel in ('report', 'annotations'):
            check(output_schema(channel))

    def test_schema_fallback_requires_explicit_parameter_rejection(self):
        unsupported = {'error': {'param': 'text.format', 'code': 'unsupported_parameter'}}
        self.assertTrue(schema_unsupported(400, unsupported))
        for status, error in ((502, unsupported), (400, {}),
                              (400, {'error': {'code': 'invalid_json_schema'}}),
                              (400, {'error': {'param': 'model', 'code': 'unsupported_value'}})):
            with self.subTest(status=status, error=error):
                self.assertFalse(schema_unsupported(status, error))

    def test_explicit_proxy_rejection_falls_back_to_validated_json(self):
        source = ['Essay.']
        formats = []
        def request(url, key, body):
            formats.append('text' in body)
            if len(formats) == 1:
                return httpx.Response(400, json={'error': {
                    'code': 'unsupported_parameter', 'param': 'text.format'}},
                    request=httpx.Request('POST', url))
            return httpx.Response(200, json={'output_text': json.dumps(report_data(source))},
                                  request=httpx.Request('POST', url))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'AI_STRUCTURED_OUTPUT': 'auto'}), \
                patch('ai_transport.request_response', side_effect=request), \
                patch.object(app.saas, 'start_call', return_value='test-call'), \
                patch.object(app.saas, 'finish_call'):
            text = app.call_openai('Essay.')
        app.validate_report(text, source)
        self.assertEqual(formats, [True, False])

    def test_structured_api_to_real_word_and_preview_then_cache_reuse(self):
        fixture = next((app.ROOT / 'tests' / 'cases').glob('*.docx'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'structured-test'
            folder.mkdir()
            (folder / 'source.docx').write_bytes(fixture.read_bytes())
            source = app.write_source_md(folder / 'source.docx', folder / 'source.md', None)
            data = report_data(source)
            app.write_meta(folder / 'meta.json', {'id': folder.name, 'status': 'queued'})
            responses = [httpx.Response(200, json={'status': 'completed', 'output_text': json.dumps(output)},
                         request=httpx.Request('POST', 'https://example.com/v1/responses'))
                         for output in ({'annotations': []}, data)]
            with patch.object(app, 'DATA', root), patch.object(accounts, 'DB', root / 'test.sqlite3'), \
                    patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'AI_STREAM': '0',
                                           'AI_STRUCTURED_OUTPUT': '1'}), \
                    patch.object(app.review_translation, 'prepare_translations', return_value={}):
                accounts.initialize()
                with patch('ai_transport.request_response', side_effect=responses) as request:
                    app.run_job(folder.name, None)
                meta = app.read_meta(folder / 'meta.json')
                self.assertEqual(meta['status'], 'succeeded', meta.get('error'))
                self.assertEqual(request.call_count, 2)
                for call in request.call_args_list:
                    self.assertTrue(call.args[2]['text']['format']['strict'])
                self.assertTrue((folder / 'graded.docx').is_file())
                self.assertEqual(app.read_meta(folder / 'report.json'), data)
                self.assertEqual((folder / 'source.docx').read_bytes(), fixture.read_bytes())
                with patch.object(app.accounts, 'owned_job', return_value={'filename': 'test.docx'}), \
                        patch.object(app.accounts, 'audit'):
                    preview = app.preview(folder.name, user={'id': 1})
                self.assertEqual(preview['channels']['report'], 'ready')
                self.assertEqual(preview['review']['evaluation']['version'], 3)
                # Simulate the missing annotation channel being recovered later.
                number, match = next((i, re.search(r'\b[A-Za-z]+\b', paragraph))
                                     for i, paragraph in enumerate(source, 1)
                                     if re.search(r'\b[A-Za-z]+\b', paragraph))
                quote = match[0]
                recovered = parse_annotations(json.dumps({'annotations': [dict(
                    paragraph=number, level='phrase', quote=quote, occurrence=1, kind='error',
                    comment='Synthetic correction used only to verify cached rendering.',
                    correction=quote + 's')]}), source)
                app.write_meta(folder / 'annotations.json', recovered)
                with patch('ai_transport.request_response') as request:
                    app.run_job(folder.name, None)
                request.assert_not_called()
                self.assertEqual(app.read_meta(folder / 'meta.json')['status'], 'succeeded')
                self.assertIn('~~' + quote + '~~{++' + quote + 's++}',
                              (folder / 'grading.md').read_text(encoding='utf-8'))
