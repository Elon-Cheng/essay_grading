# Essay Grading Studio

基于现有作文批改 Skill 的本地 Web MVP：上传 DOCX，调用 OpenAI Responses API 生成批改 Markdown，再复用仓库的 DOCX 渲染脚本生成批注版文档。

## 启动

```powershell
python -m pip install -r requirements.txt
# 在 .env 中配置 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。未配置 `OPENAI_API_KEY` 时会使用本地演示批改，便于验证上传和 DOCX 生成链路。

应用自动读取项目根目录的 `.env`，已有环境变量优先。SU8 使用 `OPENAI_BASE_URL=https://www.su8.codes/v1` 和 `OPENAI_MODEL=gpt-5.5`。配置密钥后，API 错误会使任务失败，不会返回演示批改。修改配置后需重启应用。

## API

- `POST /api/essays`：上传 `.docx`，返回任务 ID
- `GET /api/essays`：历史任务列表
- `GET /api/essays/{id}`：查询状态
- `GET /api/essays/{id}/preview`：获取原文和批改 Markdown
- `POST /api/essays/{id}/retry`：重试失败任务
- `GET /api/essays/{id}/download`：下载批注 DOCX

下载统一为 `原文件名-完整批改报告.docx`，包括完整原文、逐段反馈、综合建议、总分及 A–E 分档参考表。仅已完成且通过原文保真、报告内容与 DOCX 校验的任务可下载；缺项或损坏的旧报告需重新上传生成。浏览器接收完整文件后再保存，下载失败时在页面显示原因。

网页反馈按原文段落分组：原文及修改在上，对应点评、语言提升和问题建议紧随其后，文末单独展示总评和分数。完整学生原文可展开查看。新批改采用更连贯的自然段评语；Word 报告统一字体、段间距及评分表留白，标签与后续评语尽量保持在同一页。网页历史反馈直接使用新布局，旧 Word 文件保留原有排版。

运行时文件保存在 `data/`，不应提交到版本库。

## 用户账号与个人历史

打开网站后先注册或登录。用户名支持 3–32 位英文字母、数字及下划线（不区分大小写），密码为 8–128 位。注册成功自动进入个人工作台。

- 账号、会话、作文归属及操作日志持久化到 `data/accounts.sqlite3`。
- 密码使用独立随机盐和 scrypt 哈希保存。登录会话有效期 7 天，通过 HttpOnly、SameSite Cookie 保存；HTTPS 下启用 Secure。退出立即撤销当前会话。
- 每个账号只可访问自己的作文列表、任务状态、预览、下载与重试接口。
- 个人历史记录注册、登录、退出、上传、批改结果、预览、下载和重试，界面时间为北京时间，支持分页与刷新。
- 原有无归属的作文文件继续保留，不显示给新注册账号，也不自动分配给第一个用户。
- 备份时同时备份数据库和作文目录。可通过 `ESSAY_DATA_DIR` 指定独立数据目录。

账号接口：`POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`。个人日志：`GET /api/activity?before=<上一页游标>`。

验证命令：`python -m unittest discover -s tests -p test_accounts.py`。

## 用户权限

账号角色为普通用户（`user`）、VIP 用户（`vip`）和管理员（`admin`）。旧账号自动迁移为普通用户，公开注册始终创建普通用户。VIP 暂无额外批改额度或功能限制；管理员可以查看用户列表及修改角色，个人作文仍按账号隔离。

管理员接口：`GET /api/admin/users`、`PATCH /api/admin/users/{id}/role`，修改请求为 `{"role":"vip"}`。系统禁止降级最后一个管理员。

在实际运行应用的服务器目录执行 `python scripts/manage_user.py cyl admin`，按提示输入密码，可创建管理员；若账号已存在，会更新其密码和角色并撤销旧会话。密码不会写入脚本或命令行参数。生产操作前先备份数据库，设置 `ESSAY_DATA_DIR` 指向真实数据目录，勿以本机数据库覆盖生产库。

## SaaS V1.5

额度、订阅、支付、后台、迁移与上线步骤详见 [SAAS_V1_5.md](SAAS_V1_5.md)。免费版每月 3 次，Pro 每订阅月 100 次；售价与商户配置未完成时不开放购买。


### 词句批改与段落报告

网页批改使用两个独立 JSON 通道。`grading_contract.py` 定义报告字段及 JSON Schema；`skill_prompt.py` 读取教学规范并附加程序生成的 schema。模型只填写点评、段号、总分与分项档位，程序根据原始作文和独立批注生成 Markdown 的原文、标题、23个评价子项及三列标红表。报告 JSON 保存到 `report.json`，重试可以重新渲染而无需再调用报告模型。两路独立校验保存，批改阶段另行预生成中文译文。生成与修复默认最多3次（`AI_FORMAT_ATTEMPTS`），接口原生 schema 支持由 `AI_STRUCTURED_OUTPUT` 控制。详见 [结构化批改说明](STRUCTURED_GRADING.md)。

预览接口在处理期间即可读取，`channels.annotations` 与 `channels.report` 分别表示 pending/running/ready/failed（历史缺失批注为 unavailable）。前端沿用轮询推送效果，先显示已完成的词句结果，再显示段落报告；任一路失败保留另一份已完成结果，Word 下载仅在文档生成成功后显示。历史报告不自动补发付费请求。

中间栏词句卡片只消费 annotations，Good Point、Error、Suggestion 全部放在词句批改；暂时移除高分词栏目与额外词块学习卡片。逐段批改只消费内容、逻辑和训练反馈，Word 保留语言提升。没有批注时显示明确空态，不从 Word 修改标记伪造词句解释。

验证：`.venv/Scripts/python.exe -m unittest discover -s tests`；前端 DOM 回归：安装 linkedom 后执行 `node tests/test_annotations.cjs`（也可通过 NODE_PATH 指向外部临时依赖目录）。


### 全文综合总评

全文层按 `references/comprehensive-evaluation.md` 输出综合评价、任务回应、连贯衔接、词汇和语法五块，仍按高考25分制给总分估计及 A–E 对应标红。五层点评的分工见 `references/grading-levels.md`；短语与句子共同组成当前词句批改单元，合计以12–18条为目标。Good Point 标准与口语化教师语气由各自规范管理。旧 HTML 工作稿流程及重复的 writing-rubric 已移除，质量判断归入 scoring-rubric。

生成阶段校验五块评价及其23个必填子项、段号完整性、英文点评、分数范围和三个分项档位。程序固定生成标题与顺序；拒绝五角度诊断与词块学习卡片。预览接口的 `review.evaluation` 保留历史结构兼容。历史文件不自动重生成，旧报告的五角度诊断不在网页显示。Word 与网页使用同一份新总评内容。
