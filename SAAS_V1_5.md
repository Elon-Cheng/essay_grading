# 墨评 SaaS V1.5

## PayPro 接入评估（2026-10-03）

用户已确认需要自动到账确认、目前只有 GitHub 开源版；该版本不满足目标，自动支付接入尚未完成。后续需取得高级版实际接口，或配置已有官方商户适配的参数与 API 权限。

已检查 `codewendao/PayPro` 提交 `1880afeae3e6bd538477d93420af1d6299782a1a`。其公开版提供外部下单、支付页面和签名回调，可以开发适配；到账确认仍由管理员邮件审核，微信自动确认及支付宝当面付自动确认属于高级版。公开源码还需修正密钥日志、订单过期、减额金额与通知重试等问题，并补充真实到账交易号。尚未切换支付模式或部署 PayPro。具体协议、接入条件和源码依据见 [PAYPRO_REVIEW.md](PAYPRO_REVIEW.md)。

## wxinpay 接入状态（2026-10-03）

已重新拉取并检查用户指定的 `wxinpay/wxinpay` 仓库，最新提交仍为 `e33bc0f6190309270d641dabb3e682ead4b37949`。公开代码缺少到账监听端、可信回调协议及数据库建表脚本，不能仅通过配置接入自动支付。当前未新增 wxinpay 支付渠道、未切换支付模式、未部署第三方 PHP。继续接入需要完整服务端与监听端源码，或已部署服务的下单、查单、签名回调文档。检查详情见 [WXINPAY_REVIEW.md](WXINPAY_REVIEW.md)。

## 商户支付接入进度（2026-10-03）

用户已说明微信和支付宝均已开通。当前待确认普通商户／服务商接入方式及具体 API 产品权限，尚未配置真实商户参数或完成支付联调。参数清单和本地检查命令见 [MERCHANT_PAYMENT_SETUP.md](MERCHANT_PAYMENT_SETUP.md)。`scripts/check_payment_config.py` 只输出配置是否存在和 PEM 是否有效，不显示敏感值、不发起交易；现有普通商户适配不能直接替代小微特约商户的服务商接口。

## 临时个人收款模式

当前公布售价：Pro ¥19.90/月；Teacher ¥39.90/月。Teacher 教师端功能尚未上线，默认仅公布售价、不开放购买。后台「个人收款」可独立修改两个套餐价格与 Teacher 购买开关。已创建的订单保持原成交金额，不受之后价格调整影响。

设置 `PAYMENTS_MODE=manual` 后，新订单改用个人微信/支付宝收款码，付款凭证由管理员人工核实。原商户订单继续按原方式查单和验签，不会变成人工订单。

管理员登录 `/admin`，进入「个人收款」上传真实收款码（PNG/JPEG/WebP，最多 2 MB），填写收款人名称。Pro 售价为 ¥19.90/月，Teacher 为 ¥39.90/月；后台以元填写并保存，售价留空可暂停新购买。任一渠道有真实收款码和收款人时才开放该渠道，Teacher 还须明确开启购买。

用户下单后核对收款人和金额，扫码转账，提交付款人昵称、平台交易单号及成功截图。个人收款码不能自动确认到账；仅在管理员进入「订单与审核」，核对收款账户中的真实到账金额和交易单号、勾选确认并批准后，发放一次 Pro 订阅月（100 次）。续费顺延，截图本身不会授予会员；不同订单不可复用同渠道的到账交易号。

驳回时向用户展示原因，可补交凭证。已付款但订单支付窗口超时，仍允许提交凭证供管理员核实，支付窗口超时后不再展示收款码。订单创建时固定金额、收款人和收款码，更新配置不影响旧订单。凭证图片仅订单本人和管理员可查看。

退款须先在微信/支付宝实际转账，再在后台「登记实际退款」填写真实退款交易号、金额和原因；记录退款后撤销该订单权益。系统不会调用个人收款码退款接口，也不会将用户自称已支付当成到账。

收款码和付款凭证存放在 `data/payment-images`，随数据库和作文一起备份。官方商户支付可通过 `PAYMENTS_MODE=merchant` 恢复；此时使用原商户配置与 `PRO_PRICE_FEN`。

## 当前交付与发布边界

已实现并部署额度、订阅、订单、个人收款码与人工审核、后台、用量与成本记录、持久任务、PostgreSQL 迁移及备份工具。原微信 Native / 支付宝当面付适配保留，可在取得商户资质后切换。

免费版每自然月 3 次，Pro 每订阅月 100 次。保留之前免费版每天 1 次的规则，可用 `FREE_DAILY_QUOTA=0` 关闭日限制。教师套餐仅预留，不公开出售。权限 user/admin 与 free/pro/teacher 套餐分开；旧 vip 标记不自动转换为付费订阅，须管理员明确发放期限并填写原因。

已公布并上线售价：Pro ¥19.90/月，Teacher ¥39.90/月。个人收款模式分别存储 1990、3990 分；当前尚未上传真实收款码，因此 Pro 暂未开放下单。Teacher 默认仅展示售价、关闭购买，教师端功能尚未实现。商户模式需另行配置 `PRO_PRICE_FEN`、`TEACHER_PRICE_FEN` 和商户渠道，未配置时拒绝下单。

个人收款需管理员上传真实收款码并配置收款人、确定售价，按实际到账人工审核。若恢复商户自动支付，则还需商户 AppID、商户号/卖家 ID、密钥文件、公钥与有效 HTTPS 回调地址。商户协议测试不代表已经通过商户沙箱或真实支付联调；AI 单价和日预算仍需按供应商实际情况配置。

## 本地查看

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

页面：`/workspace`、`/pricing`、`/account`、`/orders`、`/admin`。后台要求现有管理员账号。可使用 `scripts/manage_user.py` 在实际数据库中管理管理员权限。

开发环境默认进程内立即执行；`APP_ENV=production` 强制使用独立 `python worker.py`，且没有 AI Key 会拒绝新任务。生产环境绝不返回模拟批改。开发环境模拟报告标记为 demo，排除真实报告成功率和 AI 成本。

## 数据与额度

- `DATABASE_URL` 为空：本地 SQLite；设为 PostgreSQL URI：生产 PostgreSQL。
- 数据库保存用户、会话、任务状态、订阅、额度周期/流水、AI 调用、订单、回调、退款及审计。
- DOCX、原文 Markdown、批改 Markdown、Word 报告保存在 `ESSAY_DATA_DIR/<job_id>`；JSON 仅兼容旧文件及导出，不再作为任务状态真值。
- 用户密码与旧会话保留；历史任务迁移时不自动重新请求 AI。旧队列任务标记为中断失败，需要明确重试。
- 提交时在同一事务内预占额度和创建任务；成功交付扣除，失败释放。唯一幂等键保护双击和网络重发，同键不同内容返回 409。
- 预占计入并发限制。失败重试最多三次执行，每次重新预占；失败返还；已交付任务不允许再次扣费重试。
- 原文先校验再占额度。文件最多 10 MB；解压最多 40 MB；正文 XML 最多 4 MB；正文最多 20,000 字符、100 段。
- 免费额度按北京时间自然月；Pro 按购买时间起的一订阅月。续费只发放未来周期，到期恢复免费权益，历史报告继续可访问。
- 管理员补偿只修改当前周期，不永久改变套餐；所有修改保存原因和额度流水。

短数据库事务在 SQLite 使用写锁，在 PostgreSQL 使用事务级 advisory lock，以串行化额度、支付和租约等状态更新。此版本适合初期规模；增长后可拆分为用户/订单锁，提高并发吞吐。

## 可靠任务和 AI 成本

独立 worker 从数据库领取 queued 任务；领取后设置租约，30 秒续租。过期任务按阶段恢复；若存在 started/unknown AI 调用，标记待核查并释放用户额度，禁止自动重复请求。已有完整批改 Markdown 的 Word 重试复用 AI 内容。

每一次真实 API 请求记录模型、供应商、request ID、输入/缓存输入/输出 token、耗时、价格快照和估算费用。格式修复与重试各自计费，不合并为一次。usage 缺失或单价缺失时费用为 null，不能当作零。

单价单位为每百万 token，按供应商实际费率填入；币种默认 CNY，不自动做汇率转换。日预算和每次调用预算预占同时约束，未知用量导致暂停新调用。管理员需根据渠道账单核查，并经 `/api/admin/calls/{id}/resolve` 填写原因及实际用量/费用，才能解除任务的未知调用状态。

预算是运营控制而非渠道账单硬上限。每次按实际请求字节数与最大输出 token 计算保守成本上界，并与 `AI_CALL_BUDGET_RESERVATION` 取较大值预占；上线前填写实际费率并校验。报表金额为估算值，需定期对供应商账单。

## 支付和退款

微信使用 API v3 公钥模式：配置商户签名私钥/证书序列号和微信支付公钥/公钥 ID，公钥更换时同时更新 ID 与 PEM。微信请求响应与回调均验签；回调 AES-GCM 解密后核对商户、订单、金额及币种。

支付宝使用 RSA2 公钥模式：应用私钥与支付宝公钥均使用 PEM。网关支持正式地址或配置沙箱地址，所有响应按原始 JSON 结果串验签，通知核对 AppID、seller ID、订单和金额。首期为当面付扫码，无自动续费或代扣。

订单价格与 100 次额度由服务器快照保存。回调与查单均调用同一结算事务，唯一交易号和订单权益来源保证不重复升级；迟到的成功通知仍按核实的支付处理。浏览器跳转不能开通会员。

下单结果不明时保留 creating 订单，不重新使用新单号盲目下单。worker 每分钟主动查询未结算订单，回调丢失仍可补发。订单过期后隐藏二维码，只有渠道确认关闭才标记 closed。

首期管理员可发起全额退款，撤销该订单贡献的会员周期并记录原因；同一订单仅一笔退款。结果不明时使用同一退款号重试，已受理退款通过查单跟踪；异常退款在后台标记 failed，需商户后台核查。退款撤销周期可能留下后续续费周期的空档，不自动前移其他已购买周期。已开始的批改允许完成，之后的新提交按当前有效套餐校验。

## 运营后台与指标

`/admin` 提供概览、用户/额度、任务、AI 调用、订单、退款、通知及审计。

- DAU：用户主动 pointer/key 操作产生的产品活动事件，排除后台轮询。
- 注册转化：近 30 天有访问记录的 visitor ID 到注册的比例；没有分母显示暂无数据，非自然人去重。
- 30 日转付费：注册已满 30 天的用户中，注册后 30 天内完成首付的比例。
- 任务失败率：今日创建的真实任务中，已结束任务的失败比例。
- API 错误率：今日请求中存在错误码的请求比例，包括格式校验失败。
- 成本按币种分别汇总；单次成本汇总该任务所有调用。未知费用独立显示。
- 运营数据按北京时间展示，底层 UTC epoch 保存。

## PostgreSQL 部署和迁移

先停旧应用提交入口并备份，创建空 PostgreSQL 数据库。脚本会复制源 SQLite 后升级副本，不改原库；目标存在用户或业务记录时拒绝迁移。用户 ID、任务 ID、会话和文件归属保持一致。

```powershell
.venv\Scripts\python scripts/backup_saas.py backup output/pre-migration.zip
$env:DATABASE_URL='postgresql://essay:<URL编码的密码>@127.0.0.1:5432/essay'
.venv\Scripts\python scripts/migrate_postgres.py --source data/accounts.sqlite3
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
.venv\Scripts\python worker.py
```

文件必须同步迁移至同一个 `ESSAY_DATA_DIR`。`compose.yaml` 增加 PostgreSQL 和 worker，继续挂载原 app_data；数据库不映射公网端口。生产密码使用 URL 安全随机字符串。配置文件与 PEM 需显式挂载给 app 和 worker，避免打包进镜像。

商户密钥只读挂载示例为 `deploy/compose.payments.yaml`：把 PEM 放在项目根 `secrets/`（已忽略），配置 AppID 等环境变量后，使用 `docker compose -f compose.yaml -f deploy/compose.payments.yaml up -d`。四个 PEM 文件名与 overlay 中路径保持一致。

反向代理固定 IP 为 `172.28.0.2`，uvicorn 只信任该代理；若网络段冲突，必须同步修改 compose 网络和 Dockerfile 信任 IP。

```powershell
.venv\Scripts\python scripts/check_saas_readiness.py
```

工具只输出配置存在与否，不输出密钥。它不能替代商户支付联调、worker 健康检查和备份恢复验收。

## 备份与恢复

备份数据库和作文文件前，进入维护窗口、停止 web 写入及 worker。SQLite 使用在线备份 API；PostgreSQL 使用 pg_dump（需安装客户端工具）；归档包含 SHA256 清单。备份输出不能放在 data 目录内，不覆盖已有归档。

```powershell
.venv\Scripts\python scripts/backup_saas.py backup output/backup-20261003.zip
.venv\Scripts\python scripts/backup_saas.py verify output/backup-20261003.zip
.venv\Scripts\python scripts/backup_saas.py restore output/backup-20261003.zip --target output/restore-check
```

恢复目标必须为空。SQLite 的库在 `restore-check/data/accounts.sqlite3`；PostgreSQL 的 `database.dump` 使用 pg_restore 恢复到空库。再指向恢复后的文件目录，验证登录、额度、历史记录和 Word 下载。备份包含密码哈希及会话，应存放于受控目录。

## 验收与发布

```powershell
.venv\Scripts\python -m unittest discover -s tests
# 仅使用专用空测试库；名称必须以 essay_test_ 开头。
$env:TEST_DATABASE_URL='postgresql://.../essay_test_saas'
.venv\Scripts\python -m unittest discover -s tests -p test_saas.py
```

真实付费试运行 E 的外部条件：确定售价、商户配置与有效回调域名，完成微信/支付宝沙箱或商户测试、真实小额支付/退款、订单与会员对账，以及生产部署。没有这些条件，E 保持待执行，不将本地协议测试标记为真实支付成功。

当前状态：A 的数据库、迁移和任务恢复已本地验收；B 的额度、幂等、限流与成本记录已本地验收；C 的套餐/订阅/账户页面已浏览器验收；D 的支付协议、签名及后台已本地验收，商户联调待配置；E 的发布检查、备份恢复工具已就绪，真实试运行待售价及商户环境。

官方协议参考：
- [微信 Native 下单](https://pay.wechatpay.cn/doc/v3/merchant/4012791877)
- [微信支付成功通知](https://pay.wechatpay.cn/doc/v3/merchant/4012791882)
- [微信退款查单](https://pay.wechatpay.cn/doc/v3/merchant/4012791884)
- [支付宝当面付接入](https://developer.alibaba.com/docs/doc.htm?articleId=105170&docType=1&treeId=292)
- [支付宝交易查询](https://developer.alibaba.com/docs/doc.htm?articleId=757&docType=4&treeId=180)
- [OpenAI Responses API](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create)



## SaaS V1.5 服务器发布记录（2026-10-03）

已发布至 123.57.106.87，应用目录 C:\essay-grading。生产数据库为 PostgreSQL 17.11，独立 worker 已运行。免费月额度 3 次、Pro 月额度 100 次，保留原免费每日 1 次规则。售价与商户配置暂缓，购买入口关闭。

服务器 43 项回归测试通过；迁移前的 9 个用户、13 个会话、7 条任务、46 条事件已核对，原管理员及作文文件保留。生产管理员页、统计接口、幂等提交与已有 Word 下载通过检查。

回滚备份：C:\essay-grading\backups\saas-v1.5-20261003T102021.zip。
PostgreSQL 与作文备份：C:\essay-grading\backups\saas-postgres-20261003.zip，校验通过。
临时验收账号已禁用并清除会话；AI 审计保留。发布后磁盘剩余约 317 MB。

待解决：公网域名被阿里云备案检查拦截。用户确认已备案，可能尚未接入，应在阿里云控制台核对接入备案；若接入已通过，提交工单检查拦截状态。
参考：https://help.aliyun.com/zh/ecs/user-guide/how-to-connect-a-registered-domain-name-to-alibaba-cloud。

真实 AI 验收未通过：www.su8.codes 的 gpt-5.5 短请求成功，完整批改出现空响应及超时，原因尚未确定。测试任务 15137513a8db478f8525a58b09aab1ac 保留原稿、释放额度，并在结果不确定后禁止自动重试。应核对供应商日志与接口兼容性，再做受控验证。供应商费率未填写，成本保持未知。
