"""Independent bilingual learning content; invalid cards cannot invalidate scoring."""
from typing import Annotated
from pydantic import Field
from backend.grading_contract import (Contract, EnglishText, VocabularyUpgrade, SynonymExpansion,
                                     TopicCollocation, validate_vocabulary, validate_synonyms,
                                     TopicCollocations, validate_topic_collocations, json_output)

ChineseText = Annotated[str, Field(min_length=1, max_length=4000, pattern=r'[\u3400-\u9fff]')]


class BilingualUpgrade(VocabularyUpgrade):
    original_zh: ChineseText
    replacement_zh: ChineseText
    source_sentence_zh: ChineseText
    minimal_sentence_zh: ChineseText
    example_sentence_zh: ChineseText
    reason_zh: ChineseText
    collocations_zh: list[ChineseText] = Field(min_length=2, max_length=4)


class BilingualSynonyms(SynonymExpansion):
    meaning_en: EnglishText = Field(min_length=1, max_length=200)
    synonyms_zh: list[ChineseText] = Field(min_length=3, max_length=5)


class BilingualCollocation(TopicCollocation):
    phrase_zh: ChineseText
    example_sentence_zh: ChineseText


class BilingualTopic(Contract):
    topic: EnglishText = Field(min_length=1, max_length=100)
    topic_zh: ChineseText
    items: list[BilingualCollocation] = Field(max_length=10)


class LearningModules(Contract):
    high_score_vocabulary: list[BilingualUpgrade] = Field(max_length=15)
    synonym_expansions: list[BilingualSynonyms] = Field(max_length=15)
    topic_collocations: BilingualTopic | None


def parse_learning(text, paragraphs):
    raw = json_output(text)
    if not isinstance(raw, dict):
        raise ValueError('Learning content must be a JSON object')
    output, errors = {'high_score_vocabulary': [], 'synonym_expansions': [], 'topic_collocations': None}, []
    for name, model, validate in (('high_score_vocabulary', BilingualUpgrade, validate_vocabulary),
                                  ('synonym_expansions', BilingualSynonyms, validate_synonyms)):
        items = raw.get(name)
        if not isinstance(items, list) or len(items) > 15:
            errors.append(name + ': missing or invalid array')
            continue
        accepted = []
        for index, value in enumerate(items):
            try:
                item = model.model_validate(value)
                if name == 'high_score_vocabulary' and len(item.collocations) != len(item.collocations_zh):
                    raise ValueError('Chinese collocations must align with English collocations')
                if name == 'synonym_expansions' and len(item.synonyms) != len(item.synonyms_zh):
                    raise ValueError('Chinese synonyms must align with English synonyms')
                # A unique exact quote establishes its position unambiguously.
                if name == 'high_score_vocabulary' and 1 <= item.paragraph <= len(paragraphs):
                    if paragraphs[item.paragraph - 1].count(item.source_sentence) == 1:
                        item.sentence_occurrence = 1
                validate(accepted + [item], paragraphs)
                accepted.append(item)
            except ValueError as exc:
                errors.append(f'{name}[{index}]: {str(exc)[:500]}')
        output[name] = [item.model_dump() for item in accepted]
    value = raw.get('topic_collocations')
    if value is not None:
        try:
            if not isinstance(value, dict) or not isinstance(value.get('items'), list) or len(value['items']) > 10:
                raise ValueError('Invalid topic library')
            accepted = []
            topic = BilingualTopic.model_validate({**value, 'items': []})
            for index, card in enumerate(value['items']):
                try:
                    item = BilingualCollocation.model_validate(card)
                    plain = [TopicCollocation.model_validate(entry.model_dump(exclude={'phrase_zh', 'example_sentence_zh'})) for entry in accepted + [item]]
                    validate_topic_collocations(TopicCollocations(topic=topic.topic, items=plain), paragraphs)
                    accepted.append(item)
                except ValueError as exc:
                    errors.append(f'topic_collocations.items[{index}]: {str(exc)[:500]}')
            topic.items = accepted
            output['topic_collocations'] = topic.model_dump()
        except ValueError as exc:
            errors.append('topic_collocations: ' + str(exc)[:500])
    return output, errors
