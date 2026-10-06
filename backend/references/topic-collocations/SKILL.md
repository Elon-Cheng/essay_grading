---
name: topic-collocations
description: 根据英语作文主题和原文整理可复用的话题短语与例句，建立独立话题表达库，区分原文提取和主题补充，不用于改错或同义词升级。
---

# 话题词伙

学习链路：主题识别 → 提取典型词伙 → 展示语境例句 → 积累同类作文表达。高分词找更合适的表达，近义词拓展替代选择，话题词伙围绕主题建立表达库；三者独立输出。

## 主题与选词

先依据题目与学生内容确定一个简短、明确的英文主题，如 Travel & Exploration、Education 或 Environment。缺少题目可据正文判断，不编造题目；无法可靠确定主题时 topic_collocations 返回 null。

优先选择主题相关、有迁移价值、自然且适合学生水平的完整搭配。学生原文中有效的表达优先；不足时可补充主题典型搭配，但必须明确来源。错误或生硬的原表达不要作为值得模仿的搭配；修正后的表达属于补充，不冒充原文。

排除功能词、无主题特色的普通单词、依赖当前句子才能成立的片段和机械拼接。短语一般2–6词，保留完整语义单位，兼顾动词短语、名词短语、形容词搭配与固定搭配，不为类型多样性凑条目。

例如旅行主题中，experience different cultures、gain new knowledge、broaden one's perspective 比 refreshing places 更典型、更便于复用；仍须结合作文内容筛选，不将这些例子固定用于所有主题。

## 固定输出

独立词汇积累通道的 topic_collocations 对象包含 topic、topic_zh 和 items，或为 null。每条同时提供 phrase_zh 和 example_sentence_zh，英文原样保留。每条展示两部分：

1. **话题词伙 phrase**：完整英文短语，不插入颜色、Markdown 或替换标记。
2. **示例句 example_sentence**：自然、完整、较短且贴合主题的英文句子，必须含当前短语，可因句首调整大小写，不改变词形；展示典型用法、便于模仿，避免明显超过学生水平的复杂结构。例句可不同于学生原句，但不能当作学生写过的内容或纳入评分。
   - 先确定 phrase，再把它作为完整连续文本放入例句，只围绕它组织句子，不改动内部词语、代词或词形。例如 phrase="designing our own Hanfu" 时，例句可为 By designing our own Hanfu, we can learn about traditional clothing. 不能写 Students can design their own Hanfu. 后者没有包含当前词伙。

每条另保存来源定位供后端校验：origin="source" 时 paragraph 为原始段落1起始编号，occurrence 为 phrase 在该段内的第几次完整表达出现（1起始），phrase 逐字匹配原文；origin="supplement" 时 paragraph、occurrence 均为0，不提供伪造的原文位置。

建议默认5–8条，内容少3–5条，丰富时最多10条；有效表达不足时少给或 items=[]，不强行凑数。短语去重，按主题相关性、复用价值、原文真实出现、搭配自然度、难度适中依次排序。

本模块只生成主题表达库，不纠错、不机械找同义词、不提高原文评分，不增加现有 Markdown／Word 卡片，也不授权前端变更。
