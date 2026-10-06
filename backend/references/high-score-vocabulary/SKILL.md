---
name: high-score-vocabulary
description: 为英语作文识别有语境依据的词汇提升，输出精准替换、原句对照、主题例句、替换原因和可迁移搭配。用于后端批改报告的独立词汇数据，不修改前端或按生僻程度加分。
---

# 高分词识别与提升

高分词不是生僻词，而是语义更精准、搭配更地道、语域更合适且可以迁移复用的词。通读题目与作文后，才判断替换是否有价值。

## 识别与边界

- 优先考虑重复的基础词、含义过宽、不地道的表达、语域不合适或搭配不自然的用词。
- 原词已经自然精准时保留；不机械地把 important 换成 crucial，不把 discover 一律换成 explore。discover 强调发现此前未知的事物，explore 强调主动探访、研究或考察；只有上下文支持后一含义时才替换。
- 推荐词必须保持原意、满足原句语法与搭配，并适合题目的体裁和读者。正式不等于堆砌学术词；书信、叙事等不强行学术化。
- 不以词汇难度自动提高评分。评分仍以学生原文按25分规范评定，教师提供的新词和例句不算学生原有亮点。
- 没有可靠提升项时 high_score_vocabulary 返回 []，不设最低数量，不编造问题或重复现有批注。

## 固定学习链路与输出

独立词汇积累通道在 high_score_vocabulary 数组中保存每条记录。英文内容与对应中文字段同时生成，按双语词汇积累协议组织。不要在现有 Markdown、全文五块评价或 Word 中新增卡片或标题。

1. **原词 → 推荐词**：original、replacement 保留准确大小写和词形。用词或必要的短语替换均可，不能只列脱离上下文的同义词。
2. **原文与最小替换**：paragraph 是输入原始段落的1起始编号；source_sentence 是逐字保留的完整原句；sentence_occurrence 是该句在段落内的第几次出现；word_occurrence 是 original 在该句内的第几次完整词／短语出现，均从1开始。minimal_sentence 只替换该处 original，其他字符完全不动。不要纠正其他错误、改标点或重写句式。
   - sentence_occurrence 不是句子顺序编号：即使引用的是本段第三句话，只要这句完整文本仅出现一次，就必须填1。word_occurrence 同样只数原词在所引用完整句子内的重复次数。
3. **主题例句**：example_sentence 使用推荐词形成自然完整的英文句子，可优化句式和搭配；围绕当前作文主题，但不得当作原文、添加到学生作文或参与评分。不要机械复制 minimal_sentence，也不要堆砌 in the present era、individuals 等不必要的书面表达。
4. **原因与复用**：reason 用1–3句解释原词在当前语境下的具体不足、推荐词的语义差别和适合之处，可依据精准度、语域、搭配、避免重复或表达力度；不能仅说“更高级／more advanced”。collocations 提供2–4个常见、自然、含推荐词的英文搭配，便于迁移复用。
   - 单个推荐词为规则 s 词形时，常用搭配可用词典原形，如 showcases → showcase creativity；多词推荐必须保留完整短语，如 strong desire → express a strong desire to，不只列 express a desire to。

## 示例（仅在对应语境成立时）

原句：More and more people try to discover various destinations.

- original: discover；replacement: explore
- minimal_sentence: More and more people try to explore various destinations.
- example_sentence: Travellers can explore coastal towns and learn about local food traditions.
- reason: Here, the writer means visiting and learning about places, rather than finding previously unknown destinations. Explore expresses that active engagement more precisely.
- collocations: explore possibilities; explore a concept; explore options

原词删除线、推荐词绿色、标记修改位置与加入生词本属于展示功能。本 Skill 只输出纯数据，不插入 HTML、颜色或删除线标记，不授权前端变更。
