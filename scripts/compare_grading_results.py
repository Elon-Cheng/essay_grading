"""Summarize two actual grading outputs without inferring semantic equivalence."""
import argparse
import json
import re
from collections import Counter
from pathlib import Path


def summarize(directory):
    data = json.loads((directory/'results.json').read_text(encoding='utf-8'))
    a,b = data['runs']
    rows = []
    def score(run):
        found = re.search(r'本篇文章打分估计为[：:]\s*([^\n]+)',run.get('review',{}).get('overall',''))
        return found.group(1).strip() if found else '未完成评分'
    def add(label,va,vb):
        rows.append(f'| {label} | {va} | {vb} |')
    add('状态',a['status'],b['status'])
    add('总分估计',score(a),score(b))
    add('词句批注总数',len(a.get('annotations',[])),len(b.get('annotations',[])))
    for kind in ('error','suggestion','good-point'):
        add(kind,Counter(x['kind'] for x in a.get('annotations',[]))[kind],Counter(x['kind'] for x in b.get('annotations',[]))[kind])
    for level in ('phrase','sentence'):
        add(level,Counter(x.get('level') for x in a.get('annotations',[]))[level],Counter(x.get('level') for x in b.get('annotations',[]))[level])
    add('AI请求次数（含格式修复）',len(a['calls']),len(b['calls']))
    add('供应商返回的模型名称',','.join(sorted({c.get('returned_model') or '未提供' for c in a['calls']})),
        ','.join(sorted({c.get('returned_model') or '未提供' for c in b['calls']})))
    add('耗时（秒）',a['seconds'],b['seconds'])
    key = lambda item:(item['paragraph'],item['start'],item['end'])
    aa = {key(item):item for item in a.get('annotations',[])}
    bb = {key(item):item for item in b.get('annotations',[])}
    common = aa.keys() & bb.keys()
    union = aa.keys() | bb.keys()
    metrics = {'shared_exact_ranges':len(common),'union_ranges':len(union),
               'exact_range_jaccard':round(len(common)/len(union),4) if union else None,
               'same_range_different_kind':sum(aa[k]['kind']!=bb[k]['kind'] for k in common),
               'same_range_different_correction':sum(aa[k].get('correction','')!=bb[k].get('correction','') for k in common)}
    (directory/'comparison-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    text = ['# 同一作文两次独立批改对照','',
            '原稿：2027春考冲刺班-沈霁菲-作文2-第1遍.docx。两份输入的SHA256相同，使用相同模型和相同提示词文件，各自独立调用，不复用旧批改。',
            '',f'模型：{data["model"]}。原稿SHA256：`{data["source_sha256"]}`。',
            '', '| 项目 | 批改A | 批改B |','|---|---|---|', *rows, '',
            f'完全相同的原文批注范围：{len(common)}处；两次范围合计去重后为{len(union)}处。完全相同范围的交并比为{metrics["exact_range_jaccard"]}。范围长度不同也会算不同，因此该数值不是语义一致率。',
            f'同一范围分类不同：{metrics["same_range_different_kind"]}处；同一范围改法不同：{metrics["same_range_different_correction"]}处。','', '## 原文同一范围的改法与分类差异','']
    for k in sorted(common):
        x,y = aa[k],bb[k]
        if x['kind']!=y['kind'] or x.get('correction','')!=y.get('correction',''):
            text += [f'原文：{x["quote"]}',f'- A：{x["kind"]}；改法：{x.get("correction", "无替换")}',
                     f'- B：{y["kind"]}；改法：{y.get("correction", "无替换")}','']
    for label,own,other in [('A',aa,bb),('B',bb,aa)]:
        text += [f'## 仅在{label}出现的精确批注范围','']
        for k in sorted(own.keys()-other.keys()):
            item=own[k]
            text += [f'- 第{item["paragraph"]}段 `{item["quote"]}`：{item["kind"]}。{item["comment"]}']
        text += ['']
    for run in (a,b):
        text += [f'## 批改{run["label"]}全文总评','']
        for section in run.get('review',{}).get('evaluation',{}).get('overview',[]):
            text += [f'### {section["title"]}','',section['text'],'']
    assessment = directory/'assessment.md'
    if assessment.exists():
        text += ['', assessment.read_text(encoding='utf-8'), '']
    text += ['此对照只有两次实际运行，适合检查本篇的重复批改差异，不能据此推断长期评分波动范围。']
    (directory/'comparison.md').write_text('\n'.join(text),encoding='utf-8')
    print(json.dumps({'metrics':metrics,'runs':[{k:r.get(k) for k in ('label','status','seconds','channels')} | {'score':score(r),'annotations':len(r.get('annotations',[]))} for r in (a,b)]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    summarize(parser.parse_args().directory)
