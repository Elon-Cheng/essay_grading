"""Normalize presentation-only aliases without changing student text or grading."""
import re
import json
from difflib import SequenceMatcher
from review_annotations import EVALUATION_HEADINGS
from scripts.render_grading_docx import recover_original, clean_markdown

RUBRIC = [('A','9–10','9–10','4–5'),('B','7–8','7–8','3'),
          ('C','5–6','5–6','2'),('D','3–4','3–4','1'),('E','0–2','0–2','0')]


def marked_source(paragraphs, annotations):
    """Use only validated Error anchors; suggestions never rewrite the essay."""
    result=[]
    for number, source in enumerate(paragraphs,1):
        marked=source;end_limit=len(source)
        for item in sorted((a for a in annotations if a.get('paragraph')==number and a.get('kind')=='error'),
                           key=lambda a:a.get('start',-1),reverse=True):
            start,end=item.get('start'),item.get('end');quote=item.get('quote');new=item.get('correction')
            if (type(start) is not int or type(end) is not int or not 0<=start<end<=end_limit
                    or source[start:end]!=quote or not isinstance(new,str) or new==quote):
                raise ValueError('Invalid cached Error anchor')
            if any(token in quote+new for token in ('~~','{++','++}')):
                raise ValueError('Ambiguous correction markup')
            marked=marked[:start]+'~~'+quote+'~~'+('{++'+new+'++}' if new else '')+marked[end:]
            end_limit=start
        result.append(marked)
    return result


def normalize_rubric(text):
    """Canonicalize rows, retaining explicit band choices; never infer a missing band."""
    marker='#### 全文综合评价和提升建议'
    if marker not in text:return text
    prefix,tail=text.split(marker,1)
    meta=re.search(r'^\[RUBRIC_BANDS\][ \t]*(\{[^\n]+\})[ \t]*$',tail,re.M)
    choices=None
    if meta:
        choices=json.loads(meta[1])
        if not isinstance(choices,dict) or set(choices)!= {'content','language','organization'} or any(not isinstance(v,str) or len(v)!=1 or v not in 'ABCDE' for v in choices.values()):
            raise ValueError('RUBRIC_BANDS requires explicit content/language/organization bands A–E')
        tail=tail[:meta.start()]+tail[meta.end():]
    table=re.search(r'^\|[^\n]*\|[ \t]*\n(?:\|[^\n]*\|[ \t]*(?:\n|$))+',tail,re.M)
    if table and choices is None:
        rows=[[cell.strip() for cell in line.strip().strip('|').split('|')] for line in table[0].splitlines()]
        bands=[r for r in rows if len(r)==4 and clean_markdown(r[0]) in 'ABCDE' and len(clean_markdown(r[0]))==1]
        actual={clean_markdown(r[0]):[re.sub(r'[—－-]','–',clean_markdown(c)) for c in r] for r in bands}
        if len(bands)!=5 or actual!={r[0]:list(r) for r in RUBRIC}:return text
        choices={}
        for column,key in enumerate(('content','language','organization'),1):
            selected=[clean_markdown(r[0]) for r in bands if re.fullmatch(r'\[\[red\]\].+\[\[/red\]\]',r[column])]
            if len(selected)!=1:return text
            choices[key]=selected[0]
    if choices is None:return text
    lines=['| 档次 | 内容 | 语言 | 组织结构 |','|---|---|---|---|']
    for band,*cells in RUBRIC:
        cells=[f'[[red]]{cell}[[/red]]' if choices[key]==band else cell for key,cell in zip(('content','language','organization'),cells)]
        lines.append('| '+' | '.join([band]+cells)+' |')
    rendered='\n'.join(lines)+'\n'
    tail=tail[:table.start()]+rendered+tail[table.end():] if table else tail.rstrip()+'\n\n'+rendered
    return prefix+marker+tail


def normalize_source(text, paragraphs, annotations):
    blocks=list(re.finditer(r'(^#### 原文及红色修改[ \t]*\n)(.*?)(?=^#### |\Z)',text,re.M|re.S))
    if len(blocks)!=len(paragraphs):return text
    expected=marked_source(paragraphs,annotations)
    # Never hide a reordered paragraph or a substantive unmarked rewrite.
    for index,block in enumerate(blocks):
        recovered=recover_original(block[2]);source=paragraphs[index]
        if recovered==source:continue
        ratio=SequenceMatcher(None,source,recovered,autojunk=False).ratio()
        if ratio<.92 or any(SequenceMatcher(None,p,recovered,autojunk=False).ratio()>ratio for j,p in enumerate(paragraphs) if j!=index):
            return text
    for block,marked in reversed(list(zip(blocks,expected))):
        if block[2].strip()==marked:continue
        text=text[:block.start(2)]+marked+'\n\n'+text[block.end(2):]
    return text

ALIASES = {'Comprehensive Evaluation':'综合评价', 'Overall Evaluation':'综合评价',
           'Task Response':EVALUATION_HEADINGS[1], 'Coherence and Cohesion':EVALUATION_HEADINGS[2],
           'Lexical Resource':EVALUATION_HEADINGS[3], 'Grammatical Range and Accuracy':EVALUATION_HEADINGS[4]}
FORMAT_NOTES = {'保留原文。':'Keep the original text.',
                '本段为题目标签，不计入正文词数。':'This is the task label and is excluded from the essay word count.',
                '本段为写作要求，不计入正文词数。':'This is the writing task and is excluded from the essay word count.'}


def normalize_report(text, paragraphs=None, annotations=None):
    marker='#### 全文综合评价和提升建议'
    if marker in text:
        prefix,tail=text.split(marker,1)
        def heading(match):
            name=match[1].strip().rstrip(':：')
            return '**'+ALIASES.get(name,name)+'**'
        tail=re.sub(r'^\*\*([^*\n]+)\*\*[ \t]*$',heading,tail,flags=re.M)
        text=prefix+marker+tail
    # Only fixed protocol phrases in format notes, never in source or teaching feedback.
    def note(match):
        body=match[2]
        for old,new in FORMAT_NOTES.items():body=body.replace(old,new+' ')
        return match[1]+body
    text=re.sub(r'(^#### 格式说明[ \t]*\n)(.*?)(?=^#### |\Z)',note,text,flags=re.M|re.S)
    # These obsolete display prefixes are labels, not feedback; translate no prose here.
    text=re.sub(r'(^#### (?:段落点评|问题建议)[ \t]*\n\s*)(?:段落任务与内容逻辑|展开方法与训练建议)[：:][ \t]*',r'\1',text,flags=re.M)
    text=normalize_rubric(text)
    if paragraphs is not None and annotations is not None:
        text=normalize_source(text,paragraphs,annotations)
    return text
