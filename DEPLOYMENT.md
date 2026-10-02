# 公网部署与搜索收录

## 当前上线状态

2026-10-02（北京时间）已验证 `https://english-essay-grading.online` 公网可访问，首页与 `/healthz` 返回 200，HTTP 自动跳转 HTTPS。Let's Encrypt 正式证书已签发，由 Caddy 自动续期；当前证书有效期截至 2026-12-31。

公网注册、登录、作文上传、演示批改、预览、DOCX 下载、账号隔离与退出登录验证通过。登录 Cookie 已验证包含 Secure、HttpOnly 和 SameSite=Strict，站点地图使用正式 HTTPS 地址。`EssayGradingWebsite` 与 `EssayGradingHTTPS` 开机启动任务均处于运行状态。

2026-10-02（北京时间）已切换服务器 AI 接口至 `https://www.su8.codes/v1`，配置 `OPENAI_MODEL=gpt-5.5` 和项目已有 API Key，并重启 `EssayGradingWebsite`。服务器上的鉴权模型列表请求与最小 Responses 生成请求均返回 200，生成返回 `completed` 且包含文本，耗时约 5.6 秒。切换后公网首页与 `/healthz` 返回 200，未登录访问作文接口仍返回 401。完整真实作文批改与 DOCX 生成尚未在本次检查中验证，搜索引擎提交仍需另行完成。

服务器直连 `https://api.openai.com/v1/models` 在 10 秒连接超时；此前 DNS 两次解析到不同的异常地址，提示官方直连路径存在 DNS 或网络问题，具体根因尚未确定。当前使用 SU8 中转接口，不依赖官方直连。切换前确认无排队或运行中的作文任务，原配置备份为服务器上的 `C:\essay-grading\backups\env-before-su8-20261002T095924Z.env`。API Key 不记录在本文档中。

2026-10-02 已修复真实批改 Markdown 与 DOCX 渲染器的格式协议不一致：模型输出需保留所有原始段落并使用内部修改标记；程序在转换前验证格式与原文可逆性，格式失败时最多自动修正一次。渲染器错误详情保留在服务端日志，网页显示可读提示。任务 `56b50ce78dc94b5281c5f4a6200cd5b6` 已基于其原始 DOCX 重新完成真实 AI 批改及 DOCX 生成，全部渲染校验通过，原始上传文件保持不变。发布前确认无活跃任务，代码、该任务文件和 SQLite 数据库已备份至服务器 `C:\essay-grading\backups\docx-fix-20261002T102435Z`，服务已重启。API 与账号回归测试共 12 项通过。

清理测试数据必须使用本次创建的确切账号名称及作文 ID，先核查归属与备份；不得按账号前缀或整个作文目录批量删除。本次清理曾执行过过宽范围删除；核查备份和访问日志后，未发现真实用户记录，日志中的作文均对应部署测试。

## 需要的资源

一台安装 Docker 与 Docker Compose 的 Linux 云服务器、域名 DNS 管理权限以及真实批改所用的 API Key。若使用中国大陆服务器，按服务商要求先完成域名备案。

## 发布

1. 把域名 A 记录指向服务器公网 IPv4，等待 DNS 生效。
2. 放行服务器安全组的 TCP 80、443。不要向公网开放 8000。
3. 将项目上传服务器，复制 `.env.example` 为 `.env`，填写真实域名、`PUBLIC_BASE_URL` 和 API Key。
4. 在项目目录执行 `docker compose up -d --build`。
5. Caddy 自动申请和续期 HTTPS 证书。访问 `https://你的域名/healthz` 应返回 `status: ok`。
6. 检查公开首页、注册登录、作文上传、下载，以及第二个账号不能读取第一个账号的作文。

只将可信反向代理连接到 app 容器。当前为单实例 SQLite 与后台任务架构，适合初期流量。不要在任务运行时重启应用。

账号和作文在 `app_data` 卷中持久化，升级前备份数据库和作文文件。生产环境必须先验证真实 AI 批改：未配置 API Key 时返回演示结果；已配置密钥时，模型请求失败会使任务失败，不会回退到演示结果。

## Windows Server IP 验证部署

将应用文件与 `deploy/windows` 上传到 `C:\essay-grading`，在管理员 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\essay-grading\deploy\windows\install.ps1 -PublicBaseUrl http://123.57.106.87
```

安装脚本创建独立 Python 3.13 环境、虚拟环境和 Windows 防火墙 TCP 80 入站规则。启动任务 `EssayGradingWebsite` 使用 SYSTEM 账号，开机启动、失败后一分钟重试。云服务器安全组也需要允许 TCP 80。此方式使用 HTTP，适合 IP 验证；绑定域名后再配置 HTTPS。

配置文件：`C:\essay-grading\.env`；数据：`C:\essay-grading\data`；日志：`C:\essay-grading\logs\stdout.log` 和 `stderr.log`。应用目录仅授权 SYSTEM 和 Administrators。没有配置 API Key 时使用演示批改。

```powershell
Get-ScheduledTask -TaskName EssayGradingWebsite
Invoke-RestMethod http://127.0.0.1/healthz
Get-Content C:\essay-grading\logs\stderr.log -Tail 50
```

更新前确认没有正在批改的任务，然后停止任务和其 Python 子进程，备份数据、上传代码，再重新启动：

```powershell
Disable-ScheduledTask -TaskName EssayGradingWebsite
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -in 'C:\essay-grading\.venv\Scripts\python.exe', 'C:\essay-grading-runtime\python.exe' -and $_.CommandLine -match 'uvicorn app:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Stop-ScheduledTask -TaskName EssayGradingWebsite
# 完成数据备份、上传代码或修改 .env 后启动。
Enable-ScheduledTask -TaskName EssayGradingWebsite
Start-ScheduledTask -TaskName EssayGradingWebsite
```

## Windows Server 域名与 HTTPS

当前域名：`english-essay-grading.online`，服务器：`123.57.106.87`。

DNS 添加 `@` 的 A 记录指向服务器；ECS 安全组允许 TCP 80、443 入站。服务器上的 Caddy 监听 80、443，应用仅监听 `127.0.0.1:8000`，仅信任本机反向代理头。域名 HTTP 请求跳转 HTTPS；IP 地址仍可通过 HTTP 验证。

在 `bin/caddy.exe` 放置校验过官方发布校验和的 Caddy Windows amd64 文件，然后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\essay-grading\deploy\windows\enable-https.ps1
```

脚本备份配置与数据，更新 `.env` 中的正式网站地址，注册开机启动任务 `EssayGradingHTTPS`，开放 Windows 防火墙 TCP 443。证书与续期状态保存在 `C:\essay-grading\caddy-data`，日志位于 `logs\caddy-stderr.log`。DNS 返回 NXDOMAIN 或公网端口不可达时无法签发证书，Caddy 会自动重试。

```powershell
Get-ScheduledTask -TaskName EssayGradingWebsite,EssayGradingHTTPS
Get-Content C:\essay-grading\logs\caddy-stderr.log -Tail 30
Invoke-RestMethod https://english-essay-grading.online/healthz
```

云服务器位于中国大陆时，正式通过域名提供服务还需要按阿里云要求完成域名备案。

## 搜索引擎提交

首页可以公开抓取；个人工作台与 API 不应收录。

- Google Search Console：添加域名资源，按平台生成的 TXT 记录验证 DNS，提交 `https://你的域名/sitemap.xml`。
- Bing Webmaster Tools：添加并验证站点，提交同一个 sitemap。
- 百度搜索资源平台：添加真实站点，完成平台验证，然后通过链接提交功能提交首页和 sitemap（以账号实际提供的方式为准）。

域名验证记录和提交需要站点所有者账号，无法用占位符代替。提交不保证收录或关键词排名。上线后持续发布原创英语作文点评、常见错误解析与评分标准内容，比堆砌关键词更有帮助。

## 本地检查

`python -m unittest discover -s tests -p test_accounts.py`

`docker compose config`（先填写 `.env`）

检查 `/`、`/robots.txt`、`/sitemap.xml`、`/healthz`，以及未登录请求 `/api/essays` 返回 401。
