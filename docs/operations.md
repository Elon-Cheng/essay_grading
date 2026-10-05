# 运行、备份和部署

## 本地

在项目根目录安装 `requirements.txt`，配置 `.env`。已有环境变量优先于 `.env`。

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

开发环境无 AI Key 时使用演示报告。生产环境必须配置真实批改服务；生产任务由独立 worker 处理，不返回演示报告。

```powershell
python worker.py
```

`WORKER_CONCURRENCY` 支持 1–8。任务、会话、额度和支付数据继续使用现有 `data/` 或 `ESSAY_DATA_DIR`；配置 `DATABASE_URL` 时使用 PostgreSQL。

## 备份

```powershell
python scripts/backup_saas.py backup ../essay-backup.zip
python scripts/backup_saas.py verify ../essay-backup.zip
python scripts/backup_saas.py restore ../essay-backup.zip --target ../essay-restore
```

备份位于数据目录之外。恢复目标必须为空。SQLite 备份使用数据库备份接口；PostgreSQL 需要安装 `pg_dump`。另行保护 `.env` 和商户密钥，不提交到 Git。

```powershell
python scripts/manage_user.py 用户名 admin
python scripts/check_payment_config.py
python scripts/check_saas_readiness.py
```

## 部署

Docker 构建会复制 `backend/`、`frontend/` 和必要运维脚本，排除测试、输出、数据与密钥。`compose.yaml` 保留网站、worker、PostgreSQL、Caddy；支付代理的可选配置在 `deploy/`。

```powershell
docker compose up -d --build
```

Windows 的安装、启动、数据库、HTTPS 和支付代理脚本在 `deploy/windows/`。更新时应从完整项目构建部署，不能继续使用精简前只覆盖根目录 Python 文件及 `static/` 的旧发布包。

部署前先备份现有数据。保留生产 `.env`，不要用本机数据替换生产数据库。健康检查地址仍为 `/healthz`。这次目录精简在本地完成，不自动部署线上。
