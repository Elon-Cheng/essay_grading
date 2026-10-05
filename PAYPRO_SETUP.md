# Paypro 高级版接入

> 2026-10-05：用户已取消 PayPro 接入。本文件保留为历史记录，不代表当前服务运行状态；不要据此重新启用收款。订单及批改次数相关代码保留用于历史数据兼容。

## 2026-10-05：按次购买接入

现有 Windows 服务器上的支付宝部署、密钥位置与域名操作见 [PAYPRO_WINDOWS.md](PAYPRO_WINDOWS.md)。Java 支付服务、独立数据库和 Redis 已安装运行；HTTPS 和真实收款仍以域名解析、支付宝参数和到账验收为前置条件。

按次购买与下文原有月度会员适配分离。新增 `credit_payments.py`，商品价格和次数从 `products` 读取，订单存入 `payment_orders`；商品示例为单次 2.90 元／1 次、基础 9.90 元／5 次、进阶 19.90 元／15 次，可在数据库调整。收款渠道未完成验证时，页面展示商品但禁用购买。

接口：`GET /api/payment/products`、`POST /api/payment/create`、`GET /api/payment/orders`、`GET /api/payment/{orderNo}`、`GET /api/payment/{orderNo}/status`、`POST /api/payment/callback`、`GET /api/admin/payments`。登录用户可访问 `/payment/{orderNo}`，页面每 3 秒查询本站状态。套餐、账户、订单和运营后台均接入次数购买信息。

创建订单必须带 `Idempotency-Key`，只接受 `productId` 与 `paymentMethod`，不接受客户端价格。订单保存商品名称、价格和次数快照，15 分钟过期。下单超时保留待确认订单，同一请求标识不会重建外部订单。支付回调按 PayPro 实际协议验证大写 MD5 签名、订单号、金额、备注；事务内仅入账一次，不生成订阅。`users.essay_credits` 保存尚未消耗的购买次数；预占记录沿用额度台账，批改成功扣除、失败释放。优先使用当前套餐可用额度，套餐或当天免费额度耗尽后使用购买次数。

当前 PayPro 回调仅包含原价，没有可信实际到账金额，因此关闭减额模式，不采用计划中的 9.88 元示例。本站商品 ID 不发送为 PayPro 的数字商品 ID，避免关联其另一套商品目录。晚到但已过期的订单不会自动增加次数，须核对实际到账后人工处理；重复已入账通知仍返回 success。

本机 `output/paypro-local` 的 PayPro、MySQL、Redis 已运行，状态以 2026-10-05 实际检查为准。生产服务器此前仍为人工收款模式，缺少 PayPro HTTPS 地址、共享密钥及渠道验证配置；真实收款和公网回调验收尚待这些配置到位。不能把测试回调通过当成银行真实到账。

以下保留原月度会员接入说明，供既有订单兼容。

本次适配源码：`F:/BaiduNetdiskDownload/paypro-高级版`。墨评下单到 `/api/openapi/add`，支付宝使用 `alipay_dmf`，微信使用 `wechat`；展示 Paypro 支付页面的二维码并提供打开页面按钮。签名回调 `/api/payments/paypro/notify` 核对订单、金额及备注后，事务内发放一次订阅。`transaction_id=paypro:订单号` 是 Paypro 收据标识，不是支付平台交易号。

## 部署配置

先在本机配置：已生成独立目录 `output/paypro-local`，启动和收款配置步骤见 [本机配置说明](deploy/paypro/LOCAL_SETUP.md)。生成命令为 `.venv\Scripts\python.exe scripts/setup_paypro_local.py "F:\BaiduNetdiskDownload\paypro-高级版"`；重复生成需使用新的 `--output` 目录，避免覆盖已有密钥和配置。本机 HTTP 页面不代表已完成墨评 HTTPS 购买联调。

1. 使用高级版自己的部署说明配置 MySQL、Redis、邮箱、收款二维码及支付宝当面付。替换所有演示账号和密钥；微信自动到账另需辅助程序及其配置。
2. 已对提供的源码移除签名工具中泄露密钥的日志，并修复支付宝通知不验签的问题。可通过 `python scripts/prepare_paypro.py "源码目录"` 重复应用。必须重新构建，不能使用旧镜像。当前环境缺少构建工具时，Java 编译和运行仍需在部署环境验证。
3. 关闭 `paypro.decrement.enabled`，本适配仅接受实际金额等于套餐价格的备注模式。Paypro 支付页域名使用 HTTPS，墨评回调也使用可公网访问的 HTTPS 地址。
4. 墨评 `.env` 配置 `PAYMENTS_MODE=paypro`、`PAYPRO_BASE_URL=https://支付域名`、`PAYPRO_SECRET=至少32字符随机共享密钥`，与 Paypro 的 `paypro.openapi.secret` 完全一致。配置 `PUBLIC_BASE_URL`、`PRO_PRICE_FEN=1990`，Teacher 继续遵守套餐开关。
5. 分别完成支付宝、微信真实到账验证后设置 `PAYPRO_ALIPAY_ENABLED=1`、`PAYPRO_WECHAT_ENABLED=1`，确认两个结算入口可信后设置 `PAYPRO_SETTLEMENT_VERIFIED=1` 并重启。默认均关闭，未修改当前实际 `.env`。

## 验收及边界

核对真实到账记录、墨评订阅来源、重复通知只发放一次、错误金额和签名不会开通会员。微信辅助入口的认证、金额匹配、管理员审核入口及 Paypro 通知失败重试仍需部署端验收；共享密钥只能证明通知来自 Paypro，不能独立证明银行到账。

Paypro 原通知没有真实交易号、渠道或时间戳。本适配用本地订单渠道和不可重复订单号校验通知；禁用未签名的状态查询作为结算依据。下单超时保持待确认，不重复创建外部订单。通知早于下单信息保存会被拒绝，需 Paypro 重发；该版本通知没有持久重试，丢失通知须管理员核对并重发，不能直接按扫码状态开通会员。

Paypro 无公开退款协议，自动退款入口会拒绝此类订单，需在收款账户执行退款后登记权益撤销。本机已完成 Java 构建和服务启动；次数购买代码已部署至 SaaS 服务器，真实收款、独立支付服务生产部署及微信辅助程序联调尚未完成。
