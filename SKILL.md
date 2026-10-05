---
name: english-essay-grading
description: 评阅上海高考英语作文，按25分制评分，提供词句批注、逐段反馈、全文评价、中英文切换和保留原文的 Word 批改稿。
metadata:
  short-description: 上海高考英语作文25分制教师式批改
---

# 英语作文评分批改

保留学生原意与真实水平。通读题目和全文后，定位问题、说明具体依据、给必要改法与可执行训练；不生成整篇替代范文。

## 结构与规则职责

| 职责 | 唯一规范 |
|---|---|
| 五层点评与分工 | [grading-levels.md](references/grading-levels.md) |
| 教师语气与解释方式 | [teacher-style.md](references/teacher-style.md) |
| 英文默认与预生成中文 | [feedback-language.md](references/feedback-language.md) |
| 任务判断与25分制评分 | [scoring-rubric.md](references/scoring-rubric.md) |
| 错误与优化边界 | [error-taxonomy.md](references/error-taxonomy.md) |
| 短语／句子联合批改单元 | [word-span-annotations.md](references/word-span-annotations.md) |
| Good Point 判定与分析角度 | [highlight-expression-principles.md](references/highlight-expression-principles.md) |
| 全文五块评价及子项 | [comprehensive-evaluation.md](references/comprehensive-evaluation.md) |
| 前端结构与报告协议 | [output-format.md](references/output-format.md) |
| Word 导出与交付校验 | [word-export.md](references/word-export.md) |

## 执行顺序

1. 提取原文、保留题目与段落；根据题目判断身份、读者、目的、体裁及必答要点。缺少题目时说明限制。
2. 结合完整上下文检查五层。单词问题落入词句单元；短语与句子联合选择12–18条有依据的批注，不足时据实输出。
3. 生成逐段内容／逻辑反馈与全文五块评价，按内容10、语言10、组织5内部校准，只展示总分和 A–E 对应标红。
4. 点评默认英文，批改阶段保存中文译文；局部切换不改变原文、改法、评分和定位。
5. 保真及结构校验后生成 Word，核对原始底稿、可逆原文、批改内容与格式后交付。

## 两种输出方式

- 网页：词句通道按 [web-annotations-prompt.md](references/web-annotations-prompt.md) 输出含 annotations 数组的 JSON；报告通道按 [web-grading-prompt.md](references/web-grading-prompt.md) 输出报告 JSON。grading_contract.py 是字段和 schema 的唯一来源；程序校验后保存 report.json，并根据原文与独立批注生成 grading.md，固定生成标题、23个评价子项和评分参考表。两路独立校验与保存，报告不能推导或覆盖独立批注。程序用 skill_prompt.py 组合教学规范及自动生成的 schema，网页通道不再载入 Markdown 输出指令。
- 离线 Word：读取通用规范、词句标准、全文评价、输出格式与 Word 导出规范，直接整理交付 Markdown。以本次原始 DOCX 的副本为底稿，用 scripts/render_grading_docx.py 输出新文件；source_docx_match、source_base、reversibility、content_match、format 全部为 ok 才交付。
