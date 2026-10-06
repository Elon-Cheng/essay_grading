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


class VocabularyUpgrade(Contract):
    paragraph: int = Field(ge=1)
    source_sentence: EnglishText = Field(min_length=1, max_length=4000)
    sentence_occurrence: int = Field(ge=1, le=100)
    original: EnglishText = Field(min_length=1, max_length=200)
    replacement: EnglishText = Field(min_length=1, max_length=200)
    word_occurrence: int = Field(ge=1, le=100)
    minimal_sentence: EnglishText = Field(min_length=1, max_length=4000)
    example_sentence: EnglishText = Field(min_length=1, max_length=4000)
    reason: EnglishText = Field(min_length=1, max_length=4000)
    collocations: list[EnglishText] = Field(min_length=2, max_length=4)


class SynonymExpansion(Contract):
    paragraph: int = Field(ge=1)
    original: EnglishText = Field(min_length=1, max_length=200)
    occurrence: int = Field(ge=1, le=100)
    part_of_speech: Literal['n.', 'v.', 'adj.', 'adv.', 'phr.']
    meaning_zh: str = Field(min_length=1, max_length=200, pattern=r'[\u3400-\u9fff]')
    synonyms: list[Annotated[EnglishText, Field(min_length=1, max_length=200)]] = Field(min_length=3, max_length=5)


class TopicCollocation(Contract):
    phrase: EnglishText = Field(min_length=1, max_length=200)
    example_sentence: EnglishText = Field(min_length=1, max_length=1000)
    origin: Literal['source', 'supplement']
    paragraph: int = Field(ge=0)
    occurrence: int = Field(ge=0, le=100)


class TopicCollocations(Contract):
    topic: EnglishText = Field(min_length=1, max_length=100)
    items: list[TopicCollocation] = Field(max_length=10)


class CoreReport(Contract):
    context: EnglishText = Field(min_length=1, max_length=4000)
    paragraphs: list[ParagraphFeedback]
    evaluation: Evaluation
    score: Score


class Report(CoreReport):
    # Legacy saved reports remain valid; new provider responses require the field.
    high_score_vocabulary: list[VocabularyUpgrade] = Field(default_factory=list, max_length=300)
    synonym_expansions: list[SynonymExpansion] = Field(default_factory=list, max_length=15)
    topic_collocations: TopicCollocations | None = None


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
    from backend.learning import LearningModules
    schema = {'report': CoreReport, 'annotations': Annotations, 'learning': LearningModules}[channel].model_json_schema()
    def compact(value):
        if isinstance(value, dict):
            result = {key: compact(item) for key, item in value.items() if key not in ('title', 'default')}
            if value.get('type') == 'object':
                result['required'] = list(value['properties'])
            return result
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    return compact(schema)


def schema_prompt(channel):
    if channel == 'learning':
        return ('Return only JSON matching this schema. English fields remain English; '
                'all *_zh fields must contain faithful Chinese counterparts. Do not grade the essay.\n'
                + json.dumps(output_schema(channel), ensure_ascii=False, separators=(',', ':')))
    vocabulary_note = ''
    return ('Return one JSON object matching this schema. All feedback prose must be English. '
            'Do not output Markdown headings, tables, source paragraphs or correction markup.'
            + vocabulary_note + '\n'
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
    errors = []
    for validate, value in ((validate_vocabulary, report.high_score_vocabulary),
                            (validate_synonyms, report.synonym_expansions),
                            (validate_topic_collocations, report.topic_collocations)):
        try:
            validate(value, paragraphs)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError('\n'.join(errors))
    return report


def validate_topic_collocations(library, paragraphs):
    """Check reusable units, example usage and honest source provenance."""
    if library is None:
        return
    if not library.topic.strip():
        raise ValueError('topic_collocations requires a nonempty topic')
    seen = set()
    for index, item in enumerate(library.items):
        if item.phrase != item.phrase.strip() or len(item.phrase.split()) < 2:
            raise ValueError('topic_collocations requires a complete multiword phrase')
        identity = ' '.join(item.phrase.casefold().split())
        if identity in seen:
            raise ValueError('topic_collocations contains duplicate phrases')
        seen.add(identity)
        target = r'(?<!\w)' + re.escape(item.phrase) + r'(?!\w)'
        if not re.search(target, item.example_sentence, re.I):
            raise ValueError('topic_collocations example must contain the complete phrase; '
                             f'items[{index}].example_sentence must contain {item.phrase!r} '
                             'without changing internal words, pronouns or inflections')
        if item.origin == 'source':
            if not 1 <= item.paragraph <= len(paragraphs) or item.occurrence < 1:
                raise ValueError('topic_collocations source requires a valid paragraph and occurrence')
            matches = list(re.finditer(target, paragraphs[item.paragraph - 1]))
            if item.occurrence > len(matches):
                raise ValueError('topic_collocations source phrase must match the original verbatim')
        elif item.paragraph != 0 or item.occurrence != 0:
            raise ValueError('topic_collocations supplements must not claim original source positions')


def validate_synonyms(items, paragraphs):
    """Validate source anchors and distinct alternatives; semantics follow the Skill."""
    seen = set()
    for item in items:
        if item.paragraph > len(paragraphs):
            raise ValueError('synonym_expansions paragraph is outside the source')
        if not item.original.strip() or item.original != item.original.strip():
            raise ValueError('synonym_expansions requires a nonempty original expression without outer spaces')
        target = r'(?<!\w)' + re.escape(item.original) + r'(?!\w)'
        matches = list(re.finditer(target, paragraphs[item.paragraph - 1]))
        if item.occurrence > len(matches):
            raise ValueError('synonym_expansions original must match a complete source expression verbatim')
        identity = ' '.join(item.original.casefold().split())
        if identity in seen:
            raise ValueError('synonym_expansions contains duplicate original expressions')
        seen.add(identity)
        alternatives = [' '.join(text.casefold().split()) for text in item.synonyms]
        if (any(not text.strip() or text != text.strip() for text in item.synonyms)
                or identity in alternatives or len(set(alternatives)) != len(alternatives)):
            raise ValueError('synonym_expansions requires distinct nonempty alternatives different from the original')


def validate_vocabulary(items, paragraphs):
    """Check source fidelity and single-target changes, not semantic superiority."""
    seen = set()
    for index, item in enumerate(items):
        if item.paragraph > len(paragraphs):
            raise ValueError('high_score_vocabulary paragraph is outside the source')
        for field in ('source_sentence', 'original', 'replacement', 'minimal_sentence',
                      'example_sentence', 'reason'):
            if not getattr(item, field).strip():
                raise ValueError('high_score_vocabulary requires nonempty ' + field)
        sentences = list(re.finditer(re.escape(item.source_sentence), paragraphs[item.paragraph - 1]))
        if item.sentence_occurrence > len(sentences):
            raise ValueError('high_score_vocabulary source sentence must match the original verbatim; '
                             f'items[{index}].sentence_occurrence={item.sentence_occurrence}, '
                             f'exact sentence occurs {len(sentences)} time(s) in paragraph {item.paragraph}. '
                             'Count identical occurrences, not the sentence position within the paragraph.')
        target = r'(?<!\w)' + re.escape(item.original) + r'(?!\w)'
        matches = list(re.finditer(target, item.source_sentence))
        if item.word_occurrence > len(matches):
            raise ValueError('high_score_vocabulary original must match a complete word or phrase')
        match = matches[item.word_occurrence - 1]
        identity = (item.paragraph, sentences[item.sentence_occurrence - 1].start() + match.start())
        if identity in seen:
            raise ValueError('high_score_vocabulary contains duplicate targets')
        seen.add(identity)
        if item.original.casefold() == item.replacement.casefold():
            raise ValueError('high_score_vocabulary replacement must differ from the original')
        expected = item.source_sentence[:match.start()] + item.replacement + item.source_sentence[match.end():]
        if item.minimal_sentence != expected:
            raise ValueError('high_score_vocabulary minimal sentence must change only the target; '
                             f'items[{index}].minimal_sentence must equal {expected!r}')
        recommended = r'(?<!\w)' + re.escape(item.replacement) + r'(?!\w)'
        if (item.example_sentence.strip() == item.minimal_sentence.strip()
                or not re.search(recommended, item.example_sentence)):
            raise ValueError('high_score_vocabulary needs a new example using the replacement; '
                             f'items[{index}].example_sentence must contain {item.replacement!r} '
                             'and must differ from minimal_sentence')
        collocation_pattern = r'(?<!\w)(?:' + '|'.join(re.escape(form) for form in collocation_forms(item.replacement)) + r')(?!\w)'
        if (len({text.strip().casefold() for text in item.collocations}) != len(item.collocations)
                or any(not re.search(collocation_pattern, text, re.I) for text in item.collocations)):
            raise ValueError('high_score_vocabulary needs distinct collocations using the replacement; '
                             f'items[{index}].collocations must use {item.replacement!r} or its regular s-form base. '
                             'For a multiword replacement retain the complete phrase.')


def collocation_forms(replacement):
    """Dictionary collocations may use the regular base of a single s-form word.

    This is not a general lemmatizer: multiword replacements stay intact, and
    irregular or other inflections are not guessed.
    """
    forms = [replacement]
    if not re.fullmatch(r'[A-Za-z]{4,}', replacement):
        return forms
    lower = replacement.lower()
    if lower.endswith('ies'):
        forms.append(replacement[:-3] + 'y')
    elif lower.endswith(('ches', 'shes', 'sses', 'xes', 'zes', 'oes')):
        forms.append(replacement[:-2])
    elif lower.endswith('s') and not lower.endswith('ss'):
        forms.append(replacement[:-1])
    return forms


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
