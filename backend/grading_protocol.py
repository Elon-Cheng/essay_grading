"""Repair small unmarked punctuation edits without accepting unmarked word rewrites."""
from difflib import SequenceMatcher
import re
from backend.documents import marked_paragraphs, recover_original, validate_markdown_fidelity

TOKEN = re.compile(r'~~(.*?)~~|\{\+\+(.*?)\+\+\}', re.S)
PUNCTUATION = set(' \t.,;:!?-–—\'"“”‘’()[]')


def repair_paragraph(source, marked):
    chars, positions = [], []
    cursor = 0
    for match in TOKEN.finditer(marked):
        plain = marked[cursor:match.start()]
        chars.extend(plain)
        positions.extend(range(cursor, match.start()))
        if match.group(1) is not None:
            chars.extend(match.group(1))
            positions.extend([None] * len(match.group(1)))
        cursor = match.end()
    chars.extend(marked[cursor:])
    positions.extend(range(cursor, len(marked)))
    recovered = ''.join(chars)
    if recovered != recover_original(marked) or recovered == source:
        return marked
    changes, changed_chars = [], 0
    for kind, a, b, c, d in SequenceMatcher(None, source, recovered, autojunk=False).get_opcodes():
        if kind == 'equal':
            continue
        old, new = source[a:b], recovered[c:d]
        changed_chars += len(old) + len(new)
        if changed_chars > 32 or any(x not in PUNCTUATION for x in old + new):
            return marked
        if c != d:
            mapped = positions[c:d]
            if any(x is None for x in mapped) or mapped != list(range(mapped[0], mapped[0] + len(mapped))):
                return marked
            start, end = mapped[0], mapped[-1] + 1
        else:
            anchor = positions[c] if c < len(positions) else len(marked)
            if anchor is None:
                return marked
            start = end = anchor
        replacement = ('~~' + old + '~~' if old else '') + ('{++' + new + '++}' if new else '')
        changes.append((start, end, replacement))
    fixed = marked
    for start, end, replacement in reversed(changes):
        fixed = fixed[:start] + replacement + fixed[end:]
    if recover_original(fixed) != source:
        return marked
    return fixed


def repair_punctuation(source, text):
    blocks = marked_paragraphs(text)
    if len(blocks) != len(source):
        return text
    # Locate each original block in order so identical student paragraphs stay distinct.
    cursor, result = 0, []
    for original, block in zip(source, blocks):
        start = text.find(block, cursor)
        if start < 0:
            return text
        result.append(text[cursor:start])
        result.append(repair_paragraph(original, block))
        cursor = start + len(block)
    result.append(text[cursor:])
    return ''.join(result)
