# PayPro 接入检查

更新：已取得用户提供的高级版并完成墨评 OpenAPI 适配，配置及未完成的上线验证见 [PAYPRO_SETUP.md](PAYPRO_SETUP.md)。以下为此前 GitHub 开源版的检查记录。

检查日期：2026-10-03。
仓库：https://github.com/codewendao/PayPro。
检查提交：`1880afeae3e6bd538477d93420af1d6299782a1a`。
本地源码：`output/paypro-source`（Git 忽略的检查副本）。未运行第三方服务，未连接其默认数据库或收款账号，未部署到生产。

## 结论

用户已明确目标为自动到账确认，目前只有该 GitHub 开源仓库。因此本次不推进邮件人工审核接入：现有公开版本不满足所需的自动收款能力。后续需要取得高级版实际源码／接口，或配置墨评已有官方商户适配的账号参数与 API 权限，参数清单见 [MERCHANT_PAYMENT_SETUP.md](MERCHANT_PAYMENT_SETUP.md)。

PayPro 提供了实际外部下单接口、建表 SQL、支付页面和签名回调，可以开发与墨评的适配。开源版的支付确认来自管理员邮件审核；仓库 README 的版本对比明确将微信自动确认（需辅助程序）、支付宝当面付自动确认列为高级版功能。仅部署该 GitHub 仓库无法获得自动到账确认。

墨评当前已有个人收款码、凭证、实际到账核实、退款登记与会员发放流程。接入 PayPro 开源版主要增加独立支付页面和邮件审核入口，仍须人工核实到账，并额外维护 Java、MySQL 和 Redis。若目标是自动收款，需要高级版实际源码或服务实例的协议，才能核对可信到账来源。

## 已核实的协议

- `POST /api/openapi/add`：请求包含外部订单号 `orderNo`、金额 `amount`、渠道 `payType`、毫秒时间戳、通知地址及签名；响应包含支付页面 `returnUrl`、二维码图片地址 `qrCodeUrl`、支付备注 `payNum`、原价和实际金额。
- 签名按字段名排序，排除空值和 `sign`，金额固定两位小数，末尾追加共享密钥后生成大写 MD5。
- `GET /order/state/{id}`：响应只有状态，没有签名、订单金额、渠道或平台交易号。
- `OrderServiceImpl.pass()`：管理员审核 OpenAPI 订单后，调用 `callbackFaka()` 发送 JSON 通知，然后更新订单成功状态。
- 回调字段只有 `orderNo`、`amount`、`payNum` 和 `sign`。`payNum` 是支付备注，不是微信/支付宝真实交易单号；回调没有渠道、状态或时间戳。

## 接入前需要修正的具体问题

1. `OpenApiSignUtil.generateSign()` 以 INFO 日志输出包含密钥的签名串和密钥本身。部署前删除这两处日志及其他敏感参数日志；已用过的密钥应更换。
2. `createOpenApiOrder()` 接收 `expireSeconds`，但本次检查的实现未赋值 `expireTime`。订单过期不能仅依赖接口文档；需修复并验证。
3. 减额模式会返回不同于套餐价格的 `actualAmount`，回调却发送 `money`（原价）。初期接入应关闭 `paypro.decrement.enabled`，否则必须单独保存实际应付金额并扩展到账通知。
4. `callbackFaka()` 没有验证接收方业务确认或持久重试。需增加可重试通知，墨评端按订单幂等处理；无法将当前无签名、只有状态的查单接口作为完整对账凭据。
5. 默认配置包含演示收款信息、共享密钥、数据库和邮箱配置。须逐项替换为自己的配置；MySQL、Redis 保持私网访问。真实收款码不能沿用仓库示例。
6. 开源版回调只能表示管理员批准，不能视为平台已验证的真实交易。墨评现有人工审核要求真实到账交易号，该字段需由审核端补充后才可保持相同的核实与防复用能力。

## 与墨评的适配范围

采用独立 `paypro` 支付模式，保存渠道、原价、实际应付金额、外部订单号、备注及支付页面；订单创建超时保留待确认状态。收到经验证且金额匹配的通知后，在事务中记录事件、核对真实交易号唯一性并且只发放一次订阅。浏览器跳转与扫码状态不能发放会员。退款仍需实际退款后登记，公开接口没有退款协议。

高级版需额外核实其回调签名、查单、微信辅助程序和支付宝接口权限，以及真实交易号、实际到账金额、通知重试与退款能力，不能假定与开源版完全相同。

## 源码依据

- [版本功能对比](https://github.com/codewendao/PayPro/blob/1880afeae3e6bd538477d93420af1d6299782a1a/README.md)
- [外部下单文档](https://github.com/codewendao/PayPro/blob/1880afeae3e6bd538477d93420af1d6299782a1a/OPEN_API.md)
- [下单、审核及回调实现](https://github.com/codewendao/PayPro/blob/1880afeae3e6bd538477d93420af1d6299782a1a/src/main/java/com/wendao/service/impl/OrderServiceImpl.java)
- [签名实现](https://github.com/codewendao/PayPro/blob/1880afeae3e6bd538477d93420af1d6299782a1a/src/main/java/com/wendao/utils/OpenApiSignUtil.java)

验收边界：已完成文档与源码静态检查；尚未构建或运行 PayPro，尚未完成真实支付联调。当前墨评支付模式及生产环境未切换。
