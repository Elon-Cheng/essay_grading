import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
import httpx
from backend import app
from backend import review_translation as translation


class ReviewTranslationTests(unittest.TestCase):
    def fixture(self):
        return {'original':['He go.'], 'prompt':'请写一封信。', 'channels':{'annotations':'ready','report':'running'},
                'annotations':[{'id':'P1.1','paragraph':1,'start':0,'end':6,'kind':'error',
                    'quote':'He go.','correction':'He goes.','comment':'Use goes with He.'}],
                'review':{'context':'A letter to the principal.', 'paragraphs':[
                    {'paragraph':1,'marked':'He ~~go~~{++goes++}.','feedback':[{'title':'段落点评','text':'The purpose is clear.'}]}],
                    'overall':'本篇文章打分估计为：18–19分',
                    'evaluation':{'version':3,'blocks':[{'title':'综合评价','comprehensive_sections':[
                        {'title':'Strengths','text':'The purpose is clear.'}, {'title':'Action Plan','text':'Check `He goes.`.'}]}]}}}

    def test_translation_changes_only_feedback(self):
        original=self.fixture(); snapshot=copy.deepcopy(original)
        localized=translation.apply_translation(original, {'Use goes with He.':'He 作主语时用 goes。',
            'The purpose is clear.':'写作目的清晰。','Check `He goes.`.':'检查 `He goes.`。'}, 'zh')
        self.assertEqual(original,snapshot)
        for key in ('original','prompt','channels'): self.assertEqual(localized[key],original[key])
        for key in ('quote','correction','id','paragraph','start','end','kind'):
            self.assertEqual(localized['annotations'][0][key],original['annotations'][0][key])
        self.assertEqual(localized['review']['overall'],original['review']['overall'])
        self.assertEqual(localized['review']['paragraphs'][0]['marked'],original['review']['paragraphs'][0]['marked'])
        self.assertEqual(localized['annotations'][0]['comment'],'He 作主语时用 goes。')

    def test_scoped_translation_leaves_other_feedback_in_english(self):
        original=self.fixture()
        translated=translation.apply_translation(original,{'Use goes with He.':'主谓一致。','The purpose is clear.':'目的清晰。'},'zh','annotation','P1.1')
        self.assertEqual(translated['annotations'][0]['comment'],'主谓一致。')
        self.assertEqual(translated['review'],original['review'])
        self.assertEqual(translation.translation_texts(original,'zh','annotation','P1.1'),['Use goes with He.'])
        paragraph=translation.apply_translation(original,{'The purpose is clear.':'目的清晰。'},'zh','paragraph','1')
        self.assertEqual(paragraph['review']['paragraphs'][0]['feedback'][0]['text'],'目的清晰。')
        self.assertEqual(paragraph['annotations'],original['annotations'])
        self.assertEqual(paragraph['review']['evaluation'],original['review']['evaluation'])
        block=translation.apply_translation(original,{'The purpose is clear.':'目的清晰。'},'zh','evaluation','综合评价')
        self.assertEqual(block['review']['evaluation']['blocks'][0]['comprehensive_sections'][0]['text'],'目的清晰。')
        self.assertEqual(block['review']['paragraphs'],original['review']['paragraphs'])
        with self.assertRaises(HTTPException): translation.scoped_slots(original,'annotation','invalid-id')

    def test_cache_is_bound_to_content_and_language(self):
        current=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'owned').mkdir()
            with patch.object(app,'DATA',root), patch.object(app,'preview',side_effect=lambda *a,**k:copy.deepcopy(current)), \
                patch.object(translation,'translate_texts',side_effect=lambda texts,*a:{t:'中文：'+t for t in texts}) as provider:
                translation.prepare_translations(root/'owned',current,'owned')
                first=translation.translate_review('owned',translation.TranslationRequest(language='zh'),user={})
                second=translation.translate_review('owned',translation.TranslationRequest(language='zh'),user={})
                self.assertEqual(first,second); self.assertEqual(provider.call_count,1)
                current['annotations'][0]['comment']='New feedback.'
                with self.assertRaises(HTTPException):
                    translation.translate_review('owned',translation.TranslationRequest(language='zh'),user={})
                self.assertEqual(provider.call_count,1)
                translation.prepare_translations(root/'owned',current,'owned')
                translation.translate_review('owned',translation.TranslationRequest(language='zh'),user={})
                self.assertEqual(provider.call_count,2)
                english=translation.translate_review('owned',translation.TranslationRequest(language='en'),user={})
                self.assertEqual(english['annotations'][0]['comment'],'New feedback.')
                self.assertEqual(provider.call_count,2)

    def test_ownership_is_checked_before_translation(self):
        with patch.object(app,'preview',side_effect=HTTPException(404,'Not found')), patch.object(translation,'translate_texts') as provider:
            with self.assertRaises(HTTPException):
                translation.translate_review('someone-elses-job',translation.TranslationRequest(language='zh'),user={})
            provider.assert_not_called()

    def test_failed_translation_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'owned').mkdir()
            with patch.object(app,'DATA',root), patch.object(app,'preview',return_value=self.fixture()), \
                 patch.object(translation,'translate_texts',side_effect=ValueError('Unavailable')):
                with self.assertRaises(HTTPException) as error:
                    translation.translate_review('owned',translation.TranslationRequest(language='zh'),user={})
                self.assertEqual(error.exception.status_code,409)
                self.assertEqual(list((root/'owned').iterdir()),[])
                with self.assertRaises(ValueError):
                    translation.prepare_translations(root/'owned',self.fixture(),'owned')
                self.assertFalse((root/'owned'/'prepared-zh.json').exists())

    def test_provider_preserves_quoted_examples_and_shape(self):
        def response(output):
            return httpx.Response(200,json={'output_text':json.dumps(output,ensure_ascii=False)},request=httpx.Request('POST','https://test/responses'))
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'}), patch.object(translation.saas,'start_call',return_value='test'), patch.object(translation.saas,'finish_call'):
            for invalid in ([],['检查 `He go.`。'],[None]):
                with patch.object(translation,'request_response',return_value=response(invalid)):
                    with self.assertRaises(ValueError): translation.translate_texts(['Check `He goes.`.'],'zh','job')
            with patch.object(translation,'request_response',return_value=response(['检查 `He goes.`。'])):
                result=translation.translate_texts(['Check `He goes.`.'],'zh','job')
                self.assertEqual(result['Check `He goes.`.'],'检查 `He goes.`。')

    def test_new_feedback_must_be_english(self):
        translation.validate_english_feedback(self.fixture())
        invalid=self.fixture(); invalid['annotations'][0]['comment']='应使用 goes。'
        with self.assertRaises(ValueError): translation.validate_english_feedback(invalid)
        legacy=translation.apply_translation(invalid,{},'zh')
        self.assertIn('应使用 goes。',translation.translation_texts(legacy,'en'))
