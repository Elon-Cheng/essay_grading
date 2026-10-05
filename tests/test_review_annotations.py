import json
import unittest

from backend.review_annotations import MARKER, normalize_annotations, parse_annotations, report_sections, split_response, EVALUATION_HEADINGS, LEXICAL_HEADINGS, GRAMMAR_HEADINGS, COHESION_HEADINGS, TASK_RESPONSE_HEADINGS, COMPREHENSIVE_HEADINGS, validate_evaluation


class ReviewAnnotationTests(unittest.TestCase):
    def test_single_rewritten_quote_does_not_discard_valid_annotations(self):
        source = 'Psychological lecture can help them relax in a proper way.'
        items = [
            dict(paragraph=1, level='phrase', quote='Psychological lecture', kind='error',
                 comment='缺少冠词，应改为 A psychological lecture。', correction='A psychological lecture'),
            dict(paragraph=1, level='phrase', quote='relax in a proper way', kind='suggestion',
                 comment='可以表达得更具体。'),
            dict(paragraph=1, level='sentence', quote='A psychological lecture can help them',
                 kind='error', comment='错误引用已修改原文。', correction='A psychological lecture can help them'),
            dict(paragraph=1, level='phrase', quote='lecture can help', kind='good-point', comment='重叠项'),
            None,
            dict(paragraph=1, quote='them', kind='good-point', comment='缺少层级'),
        ]
        result = parse_annotations(json.dumps(items), [source])
        self.assertEqual([a['quote'] for a in result], ['Psychological lecture', 'relax in a proper way'])
        for annotation in result:
            self.assertEqual(source[annotation['start']:annotation['end']], annotation['quote'])
        self.assertEqual(result[0]['correction'], 'A psychological lecture')
        self.assertEqual(parse_annotations('[]', [source]), [])
        with self.assertRaises(ValueError):
            parse_annotations(json.dumps(items[2:3]), [source])
        with self.assertRaises(ValueError):
            parse_annotations('not JSON', [source])

    def test_evaluation_requires_five_blocks_with_analysis_and_suggestions(self):
        report = '#### 全文综合评价和提升建议\n' + '\n\n'.join(
            f'**{title}**\n\n' + ('\n\n'.join(f'{label}：结合原文的具体内容。' for label in LEXICAL_HEADINGS) if title == 'Lexical Resource｜词汇' else '\n\n'.join(f'{label}: 结合原文的语法内容。' for label in GRAMMAR_HEADINGS) if title == 'Grammatical Range and Accuracy｜语法' else '\n\n'.join(f'{label}: 结合原文的连贯衔接内容。' for label in COHESION_HEADINGS) if title == 'Coherence and Cohesion｜连贯与衔接' else '\n\n'.join(f'{label}: 结合原文的任务回应内容。' for label in TASK_RESPONSE_HEADINGS) if title == 'Task Response｜任务回应' else '\n\n'.join(f'{label}: 结合原文的综合评价内容。' for label in COMPREHENSIVE_HEADINGS)) for title in EVALUATION_HEADINGS)
        report += '\n本篇文章打分估计为：18–19分\n| 档次 | 内容 | 语言 | 组织结构 |\n| A | 9–10 | 9–10 | [[red]]4–5[[/red]] |\n| B | [[red]]7–8[[/red]] | [[red]]7–8[[/red]] | 3 |\n| C | 5–6 | 5–6 | 2 |\n| D | 3–4 | 3–4 | 1 |\n| E | 0–2 | 0–2 | 0 |\n'
        validate_evaluation(report)
        evaluation = report_sections(report)['evaluation']
        self.assertEqual(evaluation['version'], 3)
        self.assertEqual(len(evaluation['blocks']), 5)
        self.assertEqual(evaluation['dimensions'], [])
        self.assertNotIn('本篇文章', evaluation['blocks'][-1]['suggestions'])
        self.assertEqual(evaluation['blocks'][0]['analysis'], 'Strengths：结合原文的综合评价内容。')
        comprehensive = evaluation['blocks'][0]
        self.assertEqual([s['title'] for s in comprehensive['comprehensive_sections']], list(COMPREHENSIVE_HEADINGS))
        self.assertIn('Action Plan', comprehensive['suggestions'])
        self.assertNotIn('Strengths', comprehensive['suggestions'])
        for label in COMPREHENSIVE_HEADINGS:
            for replacement in (f'{label}:', ''):
                with self.assertRaisesRegex(ValueError, 'Comprehensive Evaluation须依次包含四项'):
                    validate_evaluation(report.replace(f'{label}: 结合原文的综合评价内容。', replacement))
        with self.assertRaisesRegex(ValueError, 'Comprehensive Evaluation须依次包含四项'):
            validate_evaluation(report.replace('Strengths:', 'Enhancement Path:', 1))
        task = evaluation['blocks'][1]
        self.assertEqual([s['title'] for s in task['task_sections']], list(TASK_RESPONSE_HEADINGS))
        self.assertIn('Evidence and Examples Assessment', task['analysis'])
        self.assertNotIn('Content and Structure Optimization Suggestions', task['analysis'])
        self.assertIn('Content and Structure Optimization Suggestions', task['suggestions'])
        for label in TASK_RESPONSE_HEADINGS:
            for replacement in (f'{label}:', ''):
                with self.assertRaisesRegex(ValueError, 'Task Response须依次包含四项'):
                    validate_evaluation(report.replace(f'{label}: 结合原文的任务回应内容。', replacement))
        with self.assertRaisesRegex(ValueError, 'Task Response须依次包含四项'):
            validate_evaluation(report.replace('Position and Argument Analysis:', 'Evidence and Examples Assessment:', 1))
        self.assertEqual([s['title'] for s in evaluation['blocks'][3]['lexical_sections']], list(LEXICAL_HEADINGS))
        for label in LEXICAL_HEADINGS:
            with self.assertRaisesRegex(ValueError, 'Lexical Resource须依次包含五项'):
                validate_evaluation(report.replace(f'{label}：结合原文的具体内容。', f'{label}：'))
        self.assertEqual([s['title'] for s in evaluation['blocks'][4]['grammar_sections']], list(GRAMMAR_HEADINGS))
        self.assertEqual([s['title'] for s in evaluation['blocks'][2]['cohesion_sections']], list(COHESION_HEADINGS))
        for label in COHESION_HEADINGS:
            with self.assertRaisesRegex(ValueError, 'Coherence and Cohesion须依次包含五项'):
                validate_evaluation(report.replace(f'{label}: 结合原文的连贯衔接内容。', f'{label}:'))
            with self.assertRaisesRegex(ValueError, 'Coherence and Cohesion须依次包含五项'):
                validate_evaluation(report.replace(f'{label}: 结合原文的连贯衔接内容。', ''))
        with self.assertRaisesRegex(ValueError, 'Coherence and Cohesion须依次包含五项'):
            validate_evaluation(report.replace('Paragraph Structure:', 'Linking Devices:', 1))
        for label in GRAMMAR_HEADINGS:
            with self.assertRaisesRegex(ValueError, 'Grammatical Range and Accuracy须依次包含五项'):
                validate_evaluation(report.replace(f'{label}: 结合原文的语法内容。', f'{label}:'))
        with self.assertRaises(ValueError):
            validate_evaluation(report.replace('Sentence Variety:', 'Advanced Structures:', 1))
        with self.assertRaises(ValueError):
            validate_evaluation(report.replace('词汇范围：', '精确度：', 1))
        with self.assertRaisesRegex(ValueError, '三列各标红一个'):
            validate_evaluation(report.replace('[[red]]4–5[[/red]]','4–5'))
        for broken in [report.replace('**Task Response｜任务回应**', '**未分类**'),
                       report.replace('Action Plan: 结合原文的综合评价内容。', 'Action Plan:'),
                       report.replace('Strengths: 结合原文的综合评价内容。', 'Strengths:'),
                       report.replace('Action Plan:', '训练动作：')]:
            with self.assertRaises(ValueError):
                validate_evaluation(broken)

        old_report = report.replace('本篇文章打分估计为', '**审题与内容**\n\n旧诊断内容\n本篇文章打分估计为')
        self.assertEqual(report_sections(old_report)['evaluation']['dimensions'][0]['text'], '旧诊断内容')
        with self.assertRaisesRegex(ValueError, '不输出五角度诊断'):
            validate_evaluation(old_report)
        with self.assertRaisesRegex(ValueError, '暂不输出高分词'):
            validate_evaluation('**词块学习：make a difference**\n' + report)

    def test_legacy_overview_is_readable_but_not_accepted_for_new_grading(self):
        legacy = '#### 全文综合评价和提升建议\n' + '\n\n'.join(
            f'**{title}**\n旧报告原有内容。' for title in ('全文优势','关键问题','学习建议','提分路径'))
        evaluation = report_sections(legacy)['evaluation']
        self.assertEqual(evaluation['version'], 2)
        self.assertEqual(evaluation['blocks'], [])
        with self.assertRaises(ValueError):
            validate_evaluation(legacy)

    def test_old_evaluation_is_not_fabricated_into_five_dimensions(self):
        parsed = report_sections('#### 全文综合评价和提升建议\n原来的整段评语')['evaluation']
        self.assertEqual(parsed['version'], 1)
        self.assertEqual(parsed['dimensions'], [])

    def test_only_phrase_and_sentence_levels_are_color_annotated(self):
        items = [dict(paragraph=1, level=level, quote='very good', kind='suggestion', comment='可以更具体')
                 for level in ['word', 'paragraph', 'essay', 'phrase']]
        result = normalize_annotations(items, ['It is very good.'])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['level'], 'phrase')
        sentence = dict(paragraph=1, level='sentence', quote='We meets every Friday.',
                        kind='error', comment='主谓一致', correction='We meet every Friday.')
        result = normalize_annotations([sentence], [sentence['quote']])
        self.assertEqual(result[0]['level'], 'sentence')
        self.assertEqual(result[0]['quote'], sentence['quote'])

    def test_repeated_quote_and_unicode_are_anchored_exactly(self):
        text = '🙂 Good, very Good.'
        items = normalize_annotations([dict(paragraph=1, quote='Good', occurrence=2,
            kind='good-point', comment='准确')], [text])
        self.assertEqual(len(items), 1)
        self.assertEqual(text[items[0]['start']:items[0]['end']], 'Good')
        self.assertEqual(items[0]['start'], text.rindex('Good'))

    def test_invalid_or_overlapping_annotations_are_not_displayed(self):
        items = [dict(paragraph=1, quote='go', kind='error', comment='主谓一致', correction='goes'),
                 dict(paragraph=1, quote='He go', kind='suggestion', comment='重叠'),
                 dict(paragraph=1, quote='invented', kind='good-point', comment='虚构'),
                 dict(paragraph=True, quote='He', kind='good-point', comment='编号无效')]
        result = normalize_annotations(items, ['He go.'])
        self.assertEqual([item['quote'] for item in result], ['go'])

    def test_web_data_is_removed_from_word_markdown(self):
        report = '#### 原文及红色修改\nHe ~~go~~{++goes++}.\n'
        data = [dict(paragraph=1, quote='go', kind='error', comment='主谓一致', correction='goes')]
        grading, items = split_response(report.rstrip() + MARKER + json.dumps(data), ['He go.'])
        self.assertEqual(grading, report)
        self.assertNotIn('WEB_ANNOTATIONS', grading)
        self.assertEqual(items[0]['correction'], 'goes')
        self.assertEqual(split_response(report + MARKER + 'invalid', ['He go.'])[1], [])

    def test_legacy_reports_keep_paragraph_and_overall_feedback(self):
        report = ('#### 审题情况\n未提供题目\n#### 原文及红色修改\nEssay\n'
                  '#### 段落点评\n内容反馈\n#### 全文综合评价和提升建议\n全文反馈\n')
        parsed = report_sections(report)
        self.assertEqual(parsed['paragraphs'][0]['feedback'][0]['text'], '内容反馈')
        self.assertEqual(parsed['overall'], '全文反馈')
        self.assertEqual(parsed['context'], '未提供题目')
