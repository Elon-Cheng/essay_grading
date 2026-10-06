# 墨评 · 英语作文批改

上传 Word 作文，生成原文批注、逐段反馈、全文综合评价和完整 DOCX 批改报告。保留上海高考 25 分制、英语/中文点评切换、账号、个人历史、额度、支付与管理后台。

## 目录

```text
backend/       批改、报告协议、DOCX 生成、API、译文、账号与支付
  references/  批改教学规范与提示词
frontend/      原有 HTML、CSS、JavaScript，展示与交互
scripts/       必要运行检查、备份、迁移和恢复工具
deploy/        Windows、Docker 和可选支付代理配置
tests/         后端回归、前端 DOM 测试与固定案例
docs/          架构和运行说明
app.py         兼容 ASGI 启动入口
worker.py      兼容队列启动入口
```

前后端通过 `/api/` JSON 接口及文件下载接口连接，静态资源地址保持 `/static/`。批改与逐段批改之间的“词汇积累”页签展示高分词、近义词和话题词伙，支持 English／中文切换。

词汇由独立 `learning` 通道按三份 Skill 生成与校验，双语数据保存为任务目录内的 `learning.json`，通过预览接口提供给前端；点击语言切换不调用模型。单条校验失败只移除该条，通道失败不影响原评分和 Word 报告。历史报告没有此文件时显示空状态，不自动重生成或扣费。`AI_LEARNING_ENABLED=0` 可关闭新任务的词汇生成。

## 启动

```powershell
python -m pip install -r requirements.txt
# 复制 .env.example 为 .env，配置 AI、数据库及支付参数
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000`。开发环境未配置 `OPENAI_API_KEY` 时生成演示报告；生产环境必须配置真实服务，使用独立 `python worker.py`。`.env` 和数据仍位于项目根目录，支持 `ESSAY_DATA_DIR` 和 PostgreSQL `DATABASE_URL`。

也可使用明确的后端入口：`python -m uvicorn backend.app:app`、`python -m backend.worker`。

## 独立生成 Word

```powershell
python -m backend.documents --source-docx 作文.docx --source-md 原文.md --grading-md 批改.md --output-docx 完整报告.docx
```

该命令不启动网站，也不调用批改 API；使用已有原文和批改结果生成并校验 Word。

## 验证

```powershell
python -m unittest discover -s tests -p "test_*.py"
cd tests
npm ci --ignore-scripts
npm test
```

测试使用隔离数据目录和固定案例，不需要真实 AI 请求。前端测试依赖只安装在 `tests/node_modules/`，不进入生产镜像。

## 文档

- [架构与前后端边界](docs/architecture.md)
- [运行、备份和部署](docs/operations.md)
- [精简前后验证结果](docs/verification.md)

精简前完整状态保存在 Git 提交 `cd0d882`。历史发布包、一次性排查与研究脚本、旧说明文档已从主项目移出。运行数据、密钥、虚拟环境和生成文件不提交 Git。
