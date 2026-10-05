"""Compose channel prompts from canonical skill references, without copied rules."""
from pathlib import Path

COMMON = ('grading-levels.md', 'teacher-style.md', 'feedback-language.md', 'error-taxonomy.md')
CHANNELS = {
    'annotations': ('word-span-annotations.md', 'highlight-expression-principles.md', 'web-annotations-prompt.md'),
    'report': ('scoring-rubric.md', 'comprehensive-evaluation.md', 'web-grading-prompt.md'),
}


def prompt_files(channel):
    if channel not in CHANNELS:
        raise ValueError('Unknown grading channel')
    return COMMON + CHANNELS[channel]


def build_grading_prompt(root: Path, channel: str):
    from grading_contract import schema_prompt
    teaching = '\n\n'.join((root / 'references' / name).read_text(encoding='utf-8').strip()
                            for name in prompt_files(channel))
    return teaching + '\n\n' + schema_prompt(channel)
