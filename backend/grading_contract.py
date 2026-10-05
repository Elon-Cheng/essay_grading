"""Model supplies feedback data; Python owns the report's presentation protocol."""
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from backend.report_normalization import marked_source, RUBRIC
from backend.review_annotations import (EVALUATION_HEADINGS, COMPREHENSIVE_HEADINGS,
                                TASK_RESPONSE_HEADINGS, COHESION_HEADINGS,
                                LEXICAL_HEADINGS, GRAMMAR_HEADINGS)


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


EnglishText = Annotated[str, Field(pattern=r'^[^\u3400-\u9fff]*$')]


# This is also the source of the schema sent to the provider. No hand-copied
# schema or model-generated headings can drift from the renderer.
EVALUATION_FIELDS = (
    ('comprehensive', COMPREHENSIVE_HEADINGS,
     ('strengths', 'improvement_suggestions', 'enhancement_path', 'action_plan')),
    ('task_response', TASK_RESPONSE_HEADINGS,
     ('position_and_argument', 'evidence_and_examples', 'content_and_structure', 'improvement_suggestions')),
    ('cohesion', COHESION_HEADINGS,
     ('paragraph_structure', 'linking_devices', 'logical_flow', 'specific_improvements', 'practical_examples')),
    ('lexical', LEXICAL_HEADINGS,
     ('range', 'precision', 'style', 'improvement', 'example')),
    ('grammar', GRAMMAR_HEADINGS,
     ('sentence_variety', 'advanced_structures', 'error_patterns', 'specific_corrections', 'progressive_improvement')),
)
Evaluation = create_model('Evaluation', __base__=Contract, **{
    key: (create_model(key.title(), __base__=Contract,
                       **{field: (EnglishText, Field(min_length=1, max_length=4000)) for field in fields}), ...)
    for key, _, fields in EVALUATION_FIELDS
})


class ParagraphFeedback(Contract):
    paragraph: int = Field(ge=1)
    kind: Literal['content', 'format']
    analysis: EnglishText = Field(max_length=4000)
    language: EnglishText = Field(max_length=4000)
    suggestions: EnglishText = Field(max_length=4000)
    format_note: EnglishText = Field(max_length=1000)


class Score(Contract):
    low: float = Field(ge=0, le=25, allow_inf_nan=False)
    high: float = Field(ge=0, le=25, allow_inf_nan=False)
    content_band: Literal['A', 'B', 'C', 'D', 'E']
    language_band: Literal['A', 'B', 'C', 'D', 'E']
    organization_band: Literal['A', 'B', 'C', 'D', 'E']


class Report(Contract):
    context: EnglishText = Field(min_length=1, max_length=4000)
    paragraphs: list[ParagraphFeedback]
    evaluation: Evaluation
    score: Score


class Annotation(Contract):
    paragraph: int = Field(ge=1)
    level: Literal['phrase', 'sentence']
    quote: str = Field(min_length=1)
    occurrence: int = Field(ge=1, le=100)
    kind: Literal['good-point', 'suggestion', 'error']
    comment: EnglishText = Field(min_length=1, max_length=4000)
    correction: str = Field(max_length=4000)


class Annotations(Contract):
    annotations: list[Annotation] = Field(max_length=300)


def output_schema(channel):
    schema = {'report': Report, 'annotations': Annotations}[channel].model_json_schema()
    def compact(value):
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items() if key != 'title'}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    return compact(schema)


def schema_prompt(channel):
    return ('Return one JSON object matching this schema. All feedback prose must be English. '
            'Do not output Markdown headings, tables, source paragraphs or correction markup.\n'
            + json.dumps(output_schema(channel), ensure_ascii=False, separators=(',', ':')))


def json_output(text):
    """Accept a single fenced JSON value from compatible providers, never partial JSON."""
    text = text.strip().lstrip('\ufeff')
    fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.S | re.I)
    return json.loads(fence[1] if fence else text)


def schema_unsupported(status, data):
    """Downgrade only an explicit pre-generation unsupported-format response."""
    if status != 400 or not isinstance(data, dict):
        return False
    error = data.get('error')
    if not isinstance(error, dict):
        return False
    param = str(error.get('param') or '').lower()
    message = str(error.get('message') or '').lower()
    code = str(error.get('code') or '').lower()
    names_format = (param in {'text', 'text.format', 'response_format'}
                    or any(name in message for name in ('json_schema', 'text.format', 'response_format')))
    unsupported = (code in {'unsupported_parameter', 'unsupported_value'}
                   or any(phrase in message for phrase in ('not supported', 'unsupported', 'unknown parameter')))
    return names_format and unsupported


def parse_report(text, paragraphs):
    try:
        report = Report.model_validate(json_output(text))
    except ValidationError as exc:
        # Bound repair diagnostics and avoid copying long input objects for each error.
        errors = exc.errors(include_url=False, include_input=False)
        raise ValueError(json.dumps(errors, ensure_ascii=False, default=str)[:6000]) from None
    numbers = [item.paragraph for item in report.paragraphs]
    if sorted(numbers) != list(range(1, len(paragraphs) + 1)):
        raise ValueError('paragraphs must cover each input paragraph exactly once, numbered 1 through '
                         + str(len(paragraphs)))
    for item in report.paragraphs:
        fields = ('analysis', 'language', 'suggestions') if item.kind == 'content' else ('format_note',)
        if any(not getattr(item, field).strip() for field in fields):
            raise ValueError(f'paragraph {item.paragraph}: {item.kind} requires nonempty {fields}')
    if report.score.low > report.score.high:
        raise ValueError('score.low must not exceed score.high')
    # Strip-only content is invalid even when it passes JSON's string length rule.
    for key, _, fields in EVALUATION_FIELDS:
        if any(not getattr(getattr(report.evaluation, key), field).strip() for field in fields):
            raise ValueError(f'evaluation.{key} requires nonempty feedback in every field')
    if not report.context.strip():
        raise ValueError('context must contain the task analysis or its limitations')
    return report


def prose(value):
    # A feedback field is a paragraph, not a way to inject additional protocol
    # sections. Flatten layout and escape heading/table prefixes only.
    value = ' '.join(value.split())
    return re.sub(r'^(#{1,6}|\|)', r'\\\1', value)


def render_report(report, paragraphs, annotations=None):
    """Build legacy Markdown for the existing UI and DOCX export, without AI layout."""
    original = marked_source(paragraphs, annotations or [])
    parts = ['#### 审题情况', prose(report.context)]
    for item in sorted(report.paragraphs, key=lambda p: p.paragraph):
        parts.extend(['#### 原文及红色修改', original[item.paragraph - 1]])
        if item.kind == 'format':
            parts.extend(['#### 格式说明', prose(item.format_note)])
        else:
            for heading, field in (('段落点评', 'analysis'), ('语言提升', 'language'), ('问题建议', 'suggestions')):
                parts.extend(['#### ' + heading, prose(getattr(item, field))])
    parts.append('#### 全文综合评价和提升建议')
    for heading, (key, labels, fields) in zip(EVALUATION_HEADINGS, EVALUATION_FIELDS):
        parts.append('**' + heading + '**')
        block = getattr(report.evaluation, key)
        parts.extend(label + ': ' + prose(getattr(block, field)) for label, field in zip(labels, fields))
    score = report.score
    display = f'{score.low:g}' if score.low == score.high else f'{score.low:g}–{score.high:g}'
    parts.append('本篇文章打分估计为：' + display + '分')
    table = ['| 档次 | 内容 | 语言 | 组织结构 |', '|---|---|---|---|']
    choices = (score.content_band, score.language_band, score.organization_band)
    for band, *cells in RUBRIC:
        cells = [f'[[red]]{value}[[/red]]' if selected == band else value
                 for selected, value in zip(choices, cells)]
        table.append('| ' + ' | '.join([band] + cells) + ' |')
    parts.append('\n'.join(table))
    return '\n\n'.join(parts) + '\n'
