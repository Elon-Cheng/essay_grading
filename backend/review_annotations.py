"""Web-only annotations anchored to the unchanged student text."""
import json
import logging
import re

MARKER = '\n[WEB_ANNOTATIONS]\n'
KINDS = {'good-point', 'suggestion', 'error'}
LEVELS = {'phrase', 'sentence'}
OVERVIEW_HEADINGS = ('全文优势', '关键问题', '学习建议', '提分路径')
DIMENSION_HEADINGS = ('审题与内容', '结构与逻辑', '词汇表达', '语法准确性', '亮点表达')
EVALUATION_HEADINGS = ('综合评价', 'Task Response｜任务回应',
                       'Coherence and Cohesion｜连贯与衔接',
                       'Lexical Resource｜词汇', 'Grammatical Range and Accuracy｜语法')
logger = logging.getLogger(__name__)
LEXICAL_HEADINGS = ('词汇范围', '精确度', '学术风格', '改进方向', '举个例子')
GRAMMAR_HEADINGS = ('Sentence Variety', 'Advanced Structures', 'Error Patterns',
                    'Specific Corrections', 'Progressive Improvement')
COHESION_HEADINGS = ('Paragraph Structure', 'Linking Devices', 'Logical Flow',
                     'Specific Improvements', 'Practical Examples')
TASK_RESPONSE_HEADINGS = ('Position and Argument Analysis', 'Evidence and Examples Assessment',
                          'Content and Structure Optimization Suggestions', 'Improvement Suggestions')
COMPREHENSIVE_HEADINGS = ('Strengths', 'Improvement Suggestions', 'Enhancement Path', 'Action Plan')


def evaluation_sections(overall):
    """Project explicit headings only; never invent dimensions for old reports."""
    body = re.split(r'^本篇文章打分估计为[：:]|^\|', overall, maxsplit=1, flags=re.M)[0]
    # Recognize old headings to keep diagnostic text out of the overview.
    pattern = r'^\*\*(' + '|'.join(map(re.escape, EVALUATION_HEADINGS + OVERVIEW_HEADINGS + DIMENSION_HEADINGS)) + r')[：:]?\*\*[ \t]*\r?$'
    parts = re.split(pattern, body, flags=re.M)
    sections = [{'title': title, 'text': text.strip()} for title, text in zip(parts[1::2], parts[2::2])]
    overview = [s for s in sections if s['title'] in OVERVIEW_HEADINGS]
    complete = [s['title'] for s in overview] == list(OVERVIEW_HEADINGS) and all(s['text'] for s in overview)
    blocks = []
    for section in sections:
        if section['title'] in EVALUATION_HEADINGS:
            fields = re.fullmatch(r'分析点评[：:]\s*(.+?)\n\s*修改建议[：:]\s*(.+)', section['text'], re.S)
            block = {**section, 'analysis': fields[1].strip() if fields else '',
                     'suggestions': fields[2].strip() if fields else ''}
            detail_spec = {'综合评价': ('comprehensive_sections', COMPREHENSIVE_HEADINGS),
                           'Task Response｜任务回应': ('task_sections', TASK_RESPONSE_HEADINGS),
                           'Coherence and Cohesion｜连贯与衔接': ('cohesion_sections', COHESION_HEADINGS),
                           'Lexical Resource｜词汇': ('lexical_sections', LEXICAL_HEADINGS),
                           'Grammatical Range and Accuracy｜语法': ('grammar_sections', GRAMMAR_HEADINGS)}.get(section['title'])
            if detail_spec:
                key, headings = detail_spec
                detail = re.split(r'^(' + '|'.join(map(re.escape, headings)) + r')[：:][ \t]*', section['text'], flags=re.M)
                entries = [{'title': title, 'text': text.strip()} for title, text in zip(detail[1::2], detail[2::2])]
                if not detail[0].strip() and [s['title'] for s in entries] == list(headings) and all(s['text'] for s in entries):
                    block[key] = entries
                    split_at = 1 if key == 'comprehensive_sections' else 2 if key == 'task_sections' else 3
                    block['analysis'] = '\n\n'.join(s['title'] + '：' + s['text'] for s in entries[:split_at])
                    block['suggestions'] = '\n\n'.join(s['title'] + '：' + s['text'] for s in entries[split_at:])
            blocks.append(block)
    current_complete = ([s['title'] for s in sections] == list(EVALUATION_HEADINGS)
                        and all(s['analysis'] and s['suggestions'] for s in blocks))
    return {'version': 3 if current_complete else 2 if complete else 1, 'intro': parts[0].strip(),
            'blocks': blocks,
            'overview': overview,
            'dimensions': [s for s in sections if s['title'] in DIMENSION_HEADINGS]}


def validate_evaluation(grading):
    evaluation = report_sections(grading)['evaluation']
    if evaluation['dimensions']:
        raise ValueError('不输出五角度诊断；使用综合评价与四个写作维度')
    comprehensive = next((b for b in evaluation['blocks'] if b['title'] == '综合评价'), None)
    if comprehensive is not None and not comprehensive.get('comprehensive_sections'):
        raise ValueError('Comprehensive Evaluation须依次包含四项非空正文标签：' + '、'.join(h + ':' for h in COMPREHENSIVE_HEADINGS) + '；替代综合评价原来的分析点评和修改建议标签')
    task = next((b for b in evaluation['blocks'] if b['title'] == 'Task Response｜任务回应'), None)
    if task is not None and not task.get('task_sections'):
        raise ValueError('Task Response须依次包含四项非空正文标签：' + '、'.join(h + ':' for h in TASK_RESPONSE_HEADINGS) + '；替代该块原来的分析点评和修改建议标签')
    cohesion = next((b for b in evaluation['blocks'] if b['title'] == 'Coherence and Cohesion｜连贯与衔接'), None)
    if cohesion is not None and not cohesion.get('cohesion_sections'):
        raise ValueError('Coherence and Cohesion须依次包含五项非空正文标签：' + '、'.join(h + ':' for h in COHESION_HEADINGS) + '；替代该块原来的分析点评和修改建议标签')
    lexical = next((b for b in evaluation['blocks'] if b['title'] == 'Lexical Resource｜词汇'), None)
    if lexical is not None and not lexical.get('lexical_sections'):
        raise ValueError('Lexical Resource须依次包含五项非空正文标签：词汇范围：、精确度：、学术风格：、改进方向：、举个例子：；替代该块原来的分析点评和修改建议标签')
    grammar = next((b for b in evaluation['blocks'] if b['title'] == 'Grammatical Range and Accuracy｜语法'), None)
    if grammar is not None and not grammar.get('grammar_sections'):
        raise ValueError('Grammatical Range and Accuracy须依次包含五项非空正文标签：' + '、'.join(h + ':' for h in GRAMMAR_HEADINGS) + '；替代该块原来的分析点评和修改建议标签')
    if evaluation['version'] != 3:
        raise ValueError('全文评价须依次包含五个栏目；综合评价和Task Response各含指定四项，连贯衔接、词汇和语法块各含指定五项：' + '、'.join(EVALUATION_HEADINGS))
    rows = [[cell.strip() for cell in line.strip().strip('|').split('|')]
            for line in grading.splitlines() if line.strip().startswith('|')]
    bands = [row for row in rows if len(row) == 4 and row[0] in ('A','B','C','D','E')]
    if len(bands) != 5 or any(sum(bool(re.fullmatch(r'\[\[red\]\].+\[\[/red\]\]', row[column]))
                                 for row in bands) != 1 for column in (1,2,3)):
        raise ValueError('A–E参考表须在内容、语言、组织结构三列各标红一个本文对应单元格')
    if re.search(r'^\*\*词块学习[：:]', grading, re.M):
        raise ValueError('暂不输出高分词或词块学习卡片')


def parse_annotations(text, paragraphs):
    """Keep independently valid annotations; an invalid batch is not an empty success."""
    try:
        from backend.grading_contract import json_output
        items = json_output(text)
    except (ValueError, TypeError) as exc:
        raise ValueError('词句批注必须是包含 annotations 数组的 JSON 对象') from exc
    if isinstance(items, dict) and set(items) == {'annotations'}:
        items = items['annotations']
    if not isinstance(items, list) or len(items) > 300:
        raise ValueError('词句批注必须是最多 300 项的数组')
    candidates = [item for item in items if isinstance(item, dict) and item.get('level') in LEVELS]
    normalized = normalize_annotations(candidates, paragraphs)
    if items and not normalized:
        raise ValueError('批注层级、原文引用、位置、纠正或重叠校验失败')
    if len(normalized) != len(items):
        logger.warning('Retained %s/%s independently validated annotations; invalid items excluded',
                       len(normalized), len(items))
    return normalized


def normalize_annotations(items, paragraphs):
    result = []
    if not isinstance(items, list):
        return result
    for item in items[:300]:
        if not isinstance(item, dict):
            continue
        number = item.get('paragraph')
        quote = item.get('quote')
        kind = item.get('kind')
        level = item.get('level')
        comment = item.get('comment')
        occurrence = item.get('occurrence', 1)
        if (type(number) is not int or not 1 <= number <= len(paragraphs)
                or kind not in KINDS or (level is not None and level not in LEVELS)
                or not isinstance(quote, str) or not quote
                or not isinstance(comment, str) or not comment.strip()
                or type(occurrence) is not int or not 1 <= occurrence <= 100):
            continue
        positions = [m.start() for m in re.finditer(re.escape(quote), paragraphs[number - 1])]
        if occurrence > len(positions):
            continue
        correction = item.get('correction', '')
        if not isinstance(correction, str) or (kind == 'error' and 'correction' not in item):
            continue
        start = positions[occurrence - 1]
        end = start + len(quote)
        if any(a['paragraph'] == number and start < a['end'] and end > a['start'] for a in result):
            continue
        result.append(dict(paragraph=number, start=start, end=end, quote=quote,
                           kind=kind, comment=comment[:4000], correction=correction[:4000],
                           id=f'P{number}.{len(result) + 1}'))
        if level is not None:
            result[-1]['level'] = level
    return result


def split_response(text, paragraphs):
    report, separator, metadata = text.partition(MARKER)
    if not separator:
        return text, []
    try:
        items = json.loads(metadata.strip())
    except (ValueError, TypeError):
        items = []
    return report.rstrip() + '\n', normalize_annotations(items, paragraphs)


def report_sections(grading):
    parts = re.split(r'^####[ \t]+(.+?)[ \t]*\r?$', grading, flags=re.M)
    paragraphs, current, overall, context = [], None, '', ''
    for heading, body in zip(parts[1::2], parts[2::2]):
        body = body.strip()
        if heading == '原文及红色修改':
            current = {'marked': body, 'feedback': []}
            paragraphs.append(current)
        elif heading == '全文综合评价和提升建议':
            overall = body
            current = None
        elif current is not None:
            current['feedback'].append({'title': heading, 'text': body})
        elif heading == '审题情况':
            context = body
    return {'paragraphs': paragraphs, 'overall': overall, 'context': context,
            'evaluation': evaluation_sections(overall)}
