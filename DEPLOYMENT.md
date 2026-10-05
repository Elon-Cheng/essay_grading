# 公网部署与搜索收录

## 批改协议修复与失败任务恢复（2026-10-03）

已发布专用网页批改提示词、漏标标点修订的保真修复，以及按段落具体位置验证修订的逻辑。截图对应任务 `5c1d1dfb589c4858a3f377693df6fbdf` 已恢复成功，真实AI批改和Word生成均通过完整校验，预览及下载路由均200（服务端进程内使用所有者测试依赖）。48项回归测试通过。旧未知计费记录保留，会员额度只提交一次。备份与验证边界见 [NETWORK_STABILITY.md](NETWORK_STABILITY.md)。

## AI 网络稳定性优化（2026-10-03）

已核验本机 Jamjams、服务器端口与 su8 鉴权连接，并发布流式 Responses、明确直连、分阶段超时、低推理强度及失败调用元数据记录。完整作文测试78.03秒完成（含一次格式修正），41项回归测试通过，服务重启后健康检查200。默认推理强度的长流式测试仍失败，因此不宣称完全解决上游稳定性。域名 HTTP 403 的页面为备案拦截，HTTPS 握手被重置，仍需服务商侧处理。详情和回滚路径见 [NETWORK_STABILITY.md](NETWORK_STABILITY.md)。

## 套餐价格发布（2026-10-03）

已上线 Pro ¥19.90/月、Teacher ¥39.90/月，两个套餐价格独立配置，已创建订单保留原金额。Pro 每订阅月 100 次；Teacher 目前仅展示售价、关闭购买，教师端功能尚未实现。后台可独立调整价格和 Teacher 购买开关。生产尚未上传真实收款码，Pro 需在后台配置真实收款码及收款人后才能购买。

服务器 53 项测试通过，人工收款 10 项测试在 SQLite、PostgreSQL 均通过。线上接口和管理员配置已核验，套餐页在手机、平板、桌面宽度显示正确价格，Teacher 购买按钮禁用，无页面脚本错误或横向溢出。原账号、订单及收款配置保留。

发布前备份：`C:\essay-grading\backups\pricing-20261003T122323-code.zip`、`C:\essay-grading\backups\pricing-20261003T122323-data.zip`，备份校验通过。


## 个人收款模式发布（2026-10-03）

已在原服务器切换为 `PAYMENTS_MODE=manual`。管理员在 `/admin` →「个人收款」上传微信、支付宝真实收款码并填写收款人；售价仍留空，当前不开放购买。确定售价后在同页按元设置。

用户下单、扫码转账并提交交易单号和付款成功截图，管理员在「订单与审核」核对真实到账后开通 Pro（每订阅月 100 次）；重复审核不重复发放，同渠道交易号不能用于两个订单。退款须实际转账后再登记并撤销权益。原商户订单保持原支付方式。

本地和服务器 52 项测试通过；新增人工收款 9 项在 SQLite、PostgreSQL 均通过。浏览器验证了手机端付款凭证、后台审核、Pro 权益及响应式页面。生产管理员配置接口、页面资源、购买关闭状态已核验；没有上传任何演示收款码或修改实际售价，原账号与订单保留。

发布前代码与配置备份：`C:\essay-grading\backups\manual-20261003T121158-code.zip`。
数据库和文件备份：`C:\essay-grading\backups\manual-20261003T121158-data.zip`，校验通过。收款码、凭证以后存放在 `data/payment-images`，随数据一起备份。

## 当前上线状态

2026-10-02（北京时间）已发布段落化反馈与报告排版更新：网页按原文段落分组呈现修改和对应评语，完整原文折叠展示，文末突出综合评价与分数；新批改优先使用连贯的自然段评语。Word 统一字体、段间留白、标签与后文的分页控制及评分表单元格留白。历史网页反馈使用新布局，旧 Word 文件不重新生成。服务器端 15 项测试通过，真实批改及完整 Word 下载验证通过，测试任务为 `d10cad4849f045ed9f436dbb04991cec`。发布前已备份代码、配置和数据至 `C:\essay-grading\backups\word-report-20261002T121509Z.zip`。

2026-10-02（北京时间）已发布完整 Word 报告下载更新：文件名统一为 `原文件名-完整批改报告.docx`，生成和下载时检查原文保真、逐段反馈、综合建议、总分及统一 A–E 分档表；未完成、缺项或损坏报告拒绝下载，浏览器接收完整文件后再保存。补充 Windows 所需的 `tzdata` 依赖。服务器端 15 项回归测试通过，正式 HTTPS 页面、真实 AI 批改、DOCX 生成、完整字节下载、账号隔离和退出登录均验证通过；真实测试任务为 `d5d2e1903bfb40edb29f5d86d5f8ec2d`。演示下载测试任务为 `2f376dde96ae4c98ac20382e8f3e753d`，仅测试进程使用演示生成，生产 API 配置保持原值。发布前确认无活跃任务，代码、配置和数据备份为服务器 `C:\essay-grading\backups\word-report-20261002T110024Z.zip`。部署期间额外 PowerShell 和验证进程曾触发内存不足；关闭额外交互进程后验证通过。上游曾返回 HTTP 520，随后最小生成及真实作文批改均恢复正常。旧报告不符合完整性规范时需重新生成。

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


## SaaS V1.5 服务器发布记录（2026-10-03）

已发布至 123.57.106.87，应用目录 C:\essay-grading。生产数据库为 PostgreSQL 17.11，独立 worker 已运行。免费月额度 3 次、Pro 月额度 100 次，保留原免费每日 1 次规则。售价与商户配置暂缓，购买入口关闭。

服务器 43 项回归测试通过；迁移前的 9 个用户、13 个会话、7 条任务、46 条事件已核对，原管理员及作文文件保留。生产管理员页、统计接口、幂等提交与已有 Word 下载通过检查。

回滚备份：C:\essay-grading\backups\saas-v1.5-20261003T102021.zip。
PostgreSQL 与作文备份：C:\essay-grading\backups\saas-postgres-20261003.zip，校验通过。
临时验收账号已禁用并清除会话；AI 审计保留。发布后磁盘剩余约 317 MB。

待解决：公网域名被阿里云备案检查拦截。用户确认已备案，可能尚未接入，应在阿里云控制台核对接入备案；若接入已通过，提交工单检查拦截状态。
参考：https://help.aliyun.com/zh/ecs/user-guide/how-to-connect-a-registered-domain-name-to-alibaba-cloud。

真实 AI 验收未通过：www.su8.codes 的 gpt-5.5 短请求成功，完整批改出现空响应及超时，原因尚未确定。测试任务 15137513a8db478f8525a58b09aab1ac 保留原稿、释放额度，并在结果不确定后禁止自动重试。应核对供应商日志与接口兼容性，再做受控验证。供应商费率未填写，成本保持未知。

## 五层批改规则与页面发布（2026-10-04，北京时间）

已同步至 `123.57.106.87` 的 `C:\essay-grading`：skill、中间 Markdown 规范、网页 AI 提示词、批注解析与三栏结果页。单词层进行基础检查；短语层和句子层使用四类处理并带明确层级；段落层和全文层独立点评。句子层批注引用与实际最小纠错分别保留，最终 Word 格式不变。

发布前确认没有排队或运行中的任务，并备份受影响的 10 个文件。备份目录：`C:\essay-grading\backups\five-level-20261004T002052`。更新未包含本地 `.env`、凭据或测试用户数据，服务器原有真实 API 配置与 `gpt-5.5` 模型保留。网站和独立 worker 均已重启并处于运行状态。

服务器 5 项批注测试通过，发布文件 SHA256 校验通过；健康接口、未登录访问限制、新静态资源和既有成功报告的新预览结构检查通过。本地完整回归为 116 项通过。此次未发起新的真实 AI 批改请求，不能据此认定此前供应商完整作文响应问题已经解决。

公网 IP 健康接口返回 200；本机访问 HTTPS 域名时连接被远程关闭（WinError 10054），域名访问问题仍需另行排查。


## 四类反馈指令同步（2026-10-04，北京时间）

已同步至 `123.57.106.87` 的 `C:\essay-grading`：`SKILL.md`、`references/output-format.md`、`references/web-grading-prompt.md`。明确批改的位置、原因和改法，高分词的释义、场景及局部例句，逐段内容逻辑与可检查的训练动作，以及全文关键问题排序和下一篇训练优先级。

三个文件 SHA256 与本地发布包一致。更新前备份至 `C:\essay-grading\backups\feedback-skill-20261004T004318`。提示词在每次批改时读取，本次无需重启；网站和 worker 均运行，服务器健康检查为 200，未登录作文接口为 401。未发起新的真实 AI 批改，历史报告不重新生成。


## 词句解耦与五角度综合评价发布（2026-10-04，北京时间）

已同步 16 个应用、skill、提示词、前端及测试文件至 `123.57.106.87` 的 `C:\essay-grading`。词句批注独立生成、保存并提前展示；综合评价采用“总评＋审题与内容、结构与逻辑、词汇表达、语法准确性、亮点表达”，沿用高考25分制。网站与独立 worker 重启后均运行，健康检查200、未登录作文接口401、线上静态资源及16个文件SHA256核对通过。

发布前确认没有活跃任务，原文件备份于 `C:\essay-grading\backups\evaluation-20261004T011846`。生产环境、API配置、账号数据、服务器网络与Word渲染器保持原配置。服务器23项API及批注回归通过；新结构、两路生成模拟响应与已有成功报告的预览兼容性通过。本次没有调用真实供应商生成作文，不能据此认定上游完整作文稳定性已解决。新规则用于新生成报告，历史报告保留原内容。

## 最小词句批注范围与数量目标同步（2026-10-04，北京时间）

已通过 SSH 同步三个文件至 123.57.106.87 的 C:\essay-grading：SKILL.md、references/word-span-annotations.md、references/web-annotations-prompt.md。短语／句子批注优先引用最小必要连续片段；正常篇幅作文优先提供15–20条独立词句批注，避免重复或制造问题凑数，必要纠错不受20条限制。

服务器三个文件 SHA256 与发布包一致，原文件备份至 C:\essay-grading\backups\annotation-skill-20261004T052156Z。服务器本机健康检查返回200。提示词每次请求读取，无需重启；新批改使用新规则。此次未发起真实AI作文生成，历史报告未重新生成。

## 统一词句批改与简化全文总结发布（2026-10-04，北京时间）

已同步13个技能、提示词、解析、页面和测试文件至123.57.106.87的C:\essay-grading。Good Point、Error、Suggestion 全部归入词句批改；高分词入口和学习卡片暂时移除；新生成的全文总结仅保留全文优势、关键问题、学习建议、提分路径四项，生成校验拒绝五角度诊断及词块学习卡片。旧报告的诊断不在网页显示，已有Word文件不重新生成。

发布前确认无活跃任务，原文件备份至 C:\essay-grading\backups\feedback-format-20261004T054608Z。服务器23项相关测试通过，13个文件SHA256及实际提供的两个前端资源校验通过，网站与worker运行，健康检查200。前端DOM测试及技能校验通过。

前两次发布在测试阶段自动回滚，最终修正了PowerShell原生命令测试输出的捕获方式，并明确让接口单元测试使用其模拟的非流式请求，避免服务器AI_STREAM配置绕过模拟。生产AI和数据库配置文件未修改。本次未生成新的真实作文。

## 原文英文与中文题目分离（2026-10-04，北京时间）

已同步 static/annotations.js 和 tests/test_annotations.cjs 至服务器。前端按行将含汉字的说明移入作文题目，并合并去重已有题目；独立英文行保留在原文区。保留服务器原始段落和Unicode码点位置，批注仍准确锚定英文片段，题目批注和纯题目段落反馈不展示，字数和句数只统计原文区正文。原始DOCX和已生成Word未改写。

DOM检查覆盖混合段落、补充汉字说明、题目去重、补充字符偏移、词数和批注定位。线上脚本SHA256与本地一致、健康检查200，无需重启。原文件备份至 C:\essay-grading\backups\original-presentation-20261004T060758Z。

## 单条无效批注容错与旧报告恢复（2026-10-04，北京时间）

根因：任务 d4c5fa2c1b194011852fa3980554e3dc 的词句输出将原文 Psychological lecture 误引用为 A psychological lecture，首次18条中17条有效、自动修正后16条中15条有效；原校验一条失败即拒绝整批。已改为逐条严格原文锚定：保留有效项，排除无法匹配、层级无效、重复交叠等项；非空批次全部无效及JSON格式错误仍走原失败修复流程。提示词新增 quote 与 correction 分离的冠词实例。

已从原始保存响应恢复该任务17条有效批注，未调用AI，原稿、grading和Word的SHA256未变化；预览两通道ready，实际前端DOM呈现17张卡片、17个原文锚点，中文说明仍归题目。恢复前meta备份：C:\essay-grading\backups\annotation-recovery-d4c5fa2c1b194011852fa3980554e3dc-20261004T062233Z。

部署曾因另一篇活跃作文暂停；任务自然完成后同步14个文件并重启网站、worker。服务器25项相关测试通过；本地恢复文件保护测试和前端回归通过。部署备份：C:\essay-grading\backups\feedback-format-20261004T062240Z。公网健康200，实际前端脚本校验一致。
