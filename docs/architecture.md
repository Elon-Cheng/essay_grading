# 项目边界

项目分为后端批改与文件生成、前端渲染两个部分。浏览器通过现有 `/api/` 接口读取 JSON 和下载 DOCX；后端不依赖浏览器执行批改或生成 Word。

## 后端：`backend/`

- `app.py`：HTTP 接口、上传、任务编排、预览与下载校验。
- `grading_contract.py`、`grading_protocol.py`、`report_normalization.py`：结构化报告、原文保真及历史结果兼容。
- `documents.py`：DOCX 生成和校验，可独立命令行执行。
- `review_annotations.py`、`review_translation.py`：原文锚定批注与预生成的中英文点评。
- `skill_prompt.py`、`references/`：词句批注、全文报告、词汇积累三路独立提示词及教学规范。
- `learning.py`：高分词、近义词、话题词伙的双语结构与逐条校验。
- `worker.py`、`ai_transport.py`：持久队列、并发、API 请求与失败恢复。
- 账号、数据库、额度和支付模块：保留已有功能及数据兼容。

原文上传后分别生成词句批注和全文报告，再生成完整 Word 文档、独立双语词汇库并准备点评译文。结果分别保存为 `annotations.json`、`report.json`／`grading.md`、`graded.docx`、`learning.json` 和点评译文缓存，重试复用有效缓存。词汇中无效条目单独剔除，生成失败不影响原评分和 Word；历史报告不自动补生成词汇或扣费。

## 前端：`frontend/`

原有三栏比例、84px 评分和独立滚动保持原样。“词句批改 → 词汇积累 → 逐段批改”页签由 HTML 与 JavaScript 渲染；`learning.js`／`learning.css` 展示三个独立词汇模块并在已有中英文数据间切换，不发起翻译请求。物理目录为 `frontend/`，对外资源地址仍为 `/static/`。

前端只负责上传、轮询、展示、语言切换和下载。批改规则、分数校验、译文准备及 DOCX 生成由后端负责。

## 兼容与验证

根目录 `app.py`、`worker.py` 保留旧启动命令的兼容入口，`scripts/render_grading_docx.py` 保留旧 Word 命令的兼容入口；真正实现均位于 `backend/`。`.env`、`data/` 位置和 API 地址保持一致。

测试位于 `tests/`，DOM 测试使用版本库内的 `tests/fixtures/`，不再依赖本机 `output/` 文件。历史发布包、一次性研究脚本和旧文档已移出主项目，可从精简前的 Git 提交恢复。
