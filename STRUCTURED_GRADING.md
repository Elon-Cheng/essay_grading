# 结构化批改修复（2026-10-05）

之前的报告请求要求模型同时撰写点评、逐字复制原文、生成修改标记、排列中文协议标题和23个子项，并绘制三列标红评分表。四次并发实测的词句结果为4/4，完整报告为0/4：原文回溯失败、缺档位、表格偏差、中文点评及一次上游断流均有记录。增加重试不能消除这些格式依赖。

## 新流程

1. 词句模型返回 `{"annotations":[...]}`，沿用逐字引用、范围与重叠检查，兼容旧数组。
2. 报告模型返回 context、paragraphs、evaluation、score；不返回原文、标题或表格。
3. `grading_contract.py` 的 Pydantic 定义同时用于本地校验和 API JSON Schema。23个评价字段和三个分项档位必填，英文点评有字符约束，分数必须在0–25；逐段编号必须覆盖输入且不重复。
4. 程序使用原文和已校验 Error 批注生成修改标记，用常量生成各级标题、总分行和 A–E 表。不会从总分猜分项，不为缺失点评填模板。
5. 完成后保存 `report.json`、`grading.md`。词句补齐后，报告 JSON 可以重新渲染出包含新修改标记的 Word，无需重做全文点评。
6. 前端预览协议保持原结构。缺少任一类批改时任务不标记成功；已完成结果保留，可重试的任务显示重试按钮。

skill 的教学规则保留，网页模型不再载入 Markdown 排版协议。`references/output-format.md` 服务于程序渲染与离线 Word；两个 web prompt 和 schema 必须随代码一起发布。

## API 兼容

`AI_STRUCTURED_OUTPUT=auto`（默认）：发送 `text.format.type=json_schema` 和 `strict=true`。只有上游明确返回 HTTP 400 且指出不支持该格式参数时，才移除 API 格式参数再请求；JSON 提示词与本地校验仍然保留。普通400、断流、超时和502不会触发这种降级。

`1` 强制原生 schema；`0` 用于已知不支持此参数的接口，只使用 JSON 提示词及本地校验。原生接口用法依据 [OpenAI Structured Outputs 文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。中转是否真正执行 schema，必须通过真实调用确认。

每个通道默认最多3次生成／修复；修复只附带最近一次候选，避免反复叠加长报告。原始失败输出继续保留在 ai-rejected，成功 JSON 才写入 report.json。上游断流及计费不确定性仍遵循现有台账处理；schema 无法修复网络中断。

## 已验证的范围

- 后端全套234项测试通过；追加英文schema约束后，相关35项回归通过，其中新增1项语言约束测试。
- 真实 DOCX 输入、模拟 API JSON、完整 worker、Markdown校验、实际 Word 渲染和 preview 接口端到端通过；缓存再运行不调用 AI。
- 现有前端DOM回归及结构化报告DOM测试通过：词句卡片、逐段反馈、五块23项评价、总分和评分表均可展示。
- 原失败样本离线回放7个候选：B组两个候选保留原点评和明确评分后，通过新渲染及Word校验。A/C三个候选确实缺组织档，D两个候选存在中文点评，仍拒绝；不将它们记为成功。结果见 `output/structured-replay-20261005-v2/results.json`。
- 本地没有 `.env` 或已配置的 `OPENAI_API_KEY`，因此上述结果不代表真实模型生成成功率，也未证明线上版本已更新。

离线回放（输出目录必须是新目录）：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/replay_structured_reports.py --input output/four-grading-20261005T052920Z --output output/structured-replay-new
```

## 发布及真实验证

发布必须同时更新 app.py、grading_contract.py、skill_prompt.py、review_annotations.py、ai_transport.py、相关 references、SKILL.md，并包含上次未发布的 saas.py 与 static/app.js 状态／重试修复。grading_contract.py 还依赖现有 report_normalization.py。直接依赖已补充 `pydantic>=2.0`，Dockerfile 已改为包含所有根目录Python模块，避免漏装运行时导入。

先确认运行环境、备份代码并等待正在处理的任务结束，再更新文件并重启网页及 worker。服务更新后运行测试；用独立测试作文验证两个通道、翻译和Word，并查看 ai_calls 的错误类型与使用量。真实验证前不能把离线回放数字当作线上成功率。
