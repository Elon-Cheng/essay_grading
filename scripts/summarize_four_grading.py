import json,re,sys,itertools
from pathlib import Path
from collections import Counter
folder=Path(sys.argv[1]);data=json.loads((folder/'results.json').read_text(encoding='utf-8'))
completed=sum(r['status']=='succeeded' for r in data['runs'])
lines=['# 同一作文四次并发批改实测','',
       f'完整批改成功 {completed}/4；词句批注生成 {sum(bool(r["annotations"]) for r in data["runs"])}/4。此次证明了四路同时调用，但未验证完整批改稳定性。','',
       '样本：2027春考冲刺班-沈霁菲-作文2-第1遍.docx。四份输入 SHA256 一致，分别进入生产 worker 的队列，使用禁用测试账号，不占用真实用户额度，不复用已有批改结果。','',
       f'模型：`{data["model"]}`；推理：`{data["reasoning"]}`；worker 配置：`{data["worker_concurrency"]}`；观察到同时运行的作文：**{data["observed_peak_running"]} 篇**。','',
       '| 批改 | 状态 | 分数估计 | 总耗时 | 词句条目 | Error / Suggestion / Good Point | AI 调用 | 翻译 | Word |',
       '|---|---|---|---|---|---|---|---|---|']
events=[];costs=[]
for run in data['runs']:
    match=re.search(r'本篇文章打分估计为[：:]\s*([^\n]+)',run.get('review',{}).get('overall',''))
    run['score_summary']=match.group(1).strip() if match else '未完成'
    counts=Counter(a['kind'] for a in run['annotations']);run['annotation_counts']=dict(counts)
    translate=run['channels'].get('translation','未提供')
    lines.append(f'| {run["label"]} | {run["status"]} | {run["score_summary"]} | {run["seconds"]} 秒 | {len(run["annotations"])} | '+
                 '/'.join(str(counts[k]) for k in ('error','suggestion','good-point'))+f' | {len(run["calls"])} | {translate} | '+('已生成' if run['word_ready'] else '未生成')+' |')
    for call in run['calls']:
        if call['latency_ms'] is not None:
            events.extend([(call['started'],1),(call['started']+call['latency_ms']/1000,-1)])
        costs.append(call)
active=peak=0
for timestamp,delta in sorted(events):active+=delta;peak=max(peak,active)
lines+=['',f'AI 调用时间区间的重叠峰值：{peak} 路（按调用台账估算）。提示词在测试期间是否保持一致：{data["prompt_unchanged"]}。','',
        '## 完整性与费用','',f'真实 AI 调用共 {len(costs)} 次，输入 {sum(c["input_tokens"] or 0 for c in costs)} token，输出 {sum(c["output_tokens"] or 0 for c in costs)} token；'+
        f'{sum(c["estimated_cost"] is None for c in costs)} 次调用无法计算实际费用。',
        '任务状态 succeeded 不单独代表所有反馈完整，需同时检查词句批注、报告、翻译和 Word 文件。','']
for run in data['runs']:
    lines.append(f'- {run["label"]}：反馈通道 {json.dumps(run["channels"],ensure_ascii=False)}；额度状态 {run["quota_state"]}；'+
                 ('无任务错误。' if not run.get('error') else '错误：'+run['error']))
lines+=['','## 精确批注范围差异','',
        '| 对比 | 相同范围 | 范围交并比 | 相同范围分类不同 | 相同范围改法不同 |','|---|---|---|---|---|']
metrics=[]
for a,b in itertools.combinations(data['runs'],2):
    key=lambda item:(item['paragraph'],item['start'],item['end'])
    aa={key(x):x for x in a['annotations']};bb={key(x):x for x in b['annotations']}
    common=aa.keys()&bb.keys();union=aa.keys()|bb.keys()
    metric={'pair':a['label']+'–'+b['label'],'common':len(common),'jaccard':round(len(common)/len(union),3) if union else None,
            'kind_changes':sum(aa[k]['kind']!=bb[k]['kind'] for k in common),
            'correction_changes':sum(aa[k].get('correction','')!=bb[k].get('correction','') for k in common)}
    metrics.append(metric)
    lines.append('| '+' | '.join(str(metric[k]) for k in ('pair','common','jaccard','kind_changes','correction_changes'))+' |')
lines+=['','范围长度不同会被统计为不同批注，因此交并比不是语义一致率。单轮四次测试不能证明长期稳定性。','',
        '## 校验失败证据','']
for run in data['runs']:
    evidence=folder/('interim-'+run['label'])
    for call in run['calls']:
        if call.get('error_code') and call['error_code']!='format_validation':
            lines.append(f'- {run["label"]}：AI 调用错误 `{call["error_code"]}`，台账状态 `{call["status"]}`。')
    for path in sorted(evidence.glob('*.json')):
        if path.name in ('meta.json','annotations.json'):continue
        diagnostic=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(diagnostic,dict) and diagnostic.get('error'):
            lines.append(f'- {run["label"]}：{diagnostic["error"]}（[原始诊断]({path.relative_to(folder).as_posix()})）。')
lines+=['','未通过校验的候选报告不作为有效评分，不纳入分数一致性比较。','',
        '## 输出文件','']
for run in data['runs']:
    label=run['label']
    links=[f'[{title}]({label}/{name})' for name,title in (('grading.md','批改文本'),('annotations.json','词句批注'),('graded.docx','Word')) if (folder/label/name).is_file()]
    lines.append(f'- {label}：'+('、'.join(links) if links else '无已完成反馈文件')+'。')
data['pairwise_metrics']=metrics;data['ai_interval_peak']=peak
(folder/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(folder/'comparison-metrics.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('\n'.join(lines[:17]))
