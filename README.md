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
