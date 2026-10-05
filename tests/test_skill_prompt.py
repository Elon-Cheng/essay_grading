import tempfile
import unittest
from pathlib import Path
from skill_prompt import build_grading_prompt, prompt_files

ROOT=Path(__file__).resolve().parent.parent

class SkillPromptTests(unittest.TestCase):
    def test_channels_load_shared_and_specific_rules(self):
        annotation=build_grading_prompt(ROOT,'annotations')
        report=build_grading_prompt(ROOT,'report')
        self.assertIn('12–18',annotation)
        self.assertIn('Good Point 尤其口语化',annotation)
        self.assertIn('唯一顶层字段 annotations',annotation)
        self.assertNotIn('## 总分与 A–E 表',annotation)
        self.assertNotIn('output-format.md',prompt_files('report'))
        self.assertIn('不要返回学生原文',report)
        self.assertIn('"additionalProperties":false',report)
        self.assertIn('Grammatical Range and Accuracy',report)
        self.assertNotIn('唯一顶层字段 annotations',report)
        self.assertEqual(len(prompt_files('report')),len(set(prompt_files('report'))))

    def test_reference_changes_are_loaded_without_copied_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'references').mkdir()
            for name in prompt_files('annotations'):
                (root/'references'/name).write_text(name,encoding='utf-8')
            style=root/'references/teacher-style.md'
            style.write_text('Updated teacher voice.',encoding='utf-8')
            self.assertIn('Updated teacher voice.',build_grading_prompt(root,'annotations'))
            style.write_text('Second update.',encoding='utf-8')
            self.assertIn('Second update.',build_grading_prompt(root,'annotations'))
        with self.assertRaises(ValueError):prompt_files('unknown')
