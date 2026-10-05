# 微信与支付宝商户支付接入

使用用户提供的 Paypro 高级版时，请按 [PAYPRO_SETUP.md](PAYPRO_SETUP.md) 配置独立 `paypro` 模式；下文为官方商户直连模式。

用户已说明微信和支付宝均已开通（2026-10-03）。当前需要确认接口授权方式并配置真实部署环境。本文与本地检查工具的就绪结果不代表完成真实支付联调。

## 当前适配范围

`payments.py` 支持微信普通商户 API v3 Native、支付宝 RSA2 公钥模式当面付。支付成功通知和主动查单进入同一结算事务，核对订单、金额、交易号后发放一次订阅；重复通知不会重复发放。

微信小微商户若通过服务商接入，需要服务商或合作伙伴接口，不能把子商户号直接填成普通商户号。支付宝若仅开通电脑网站支付，需调整下单适配，不能用当面付接口代替。首先确认后台可以自行设置 API 密钥，以及所批准的支付产品；若使用服务商，提供服务商名称和接口文档即可，不提供其私钥。

## 普通商户模式参数

在实际服务器的 `.env` 配置以下项目，私钥保存在服务器本地 `secrets/`，不要发到聊天或提交到仓库。

| 平台 | 环境变量 | 参数来源 |
| --- | --- | --- |
| 微信 | `WECHAT_APP_ID` | 与商户号绑定的公众号、小程序或应用 AppID |
| 微信 | `WECHAT_MCH_ID` | 商户号 |
| 微信 | `WECHAT_SERIAL` | 商户 API 证书序列号 |
| 微信 | `WECHAT_PRIVATE_KEY_PATH` | 商户签名私钥 PEM 路径 |
| 微信 | `WECHAT_API_V3_KEY` | API v3 密钥，32 字节 |
| 微信 | `WECHAT_PUBLIC_KEY_ID` | 微信支付公钥 ID |
| 微信 | `WECHAT_PUBLIC_KEY_PATH` | 微信支付公钥 PEM 路径，与公钥 ID 对应 |
| 支付宝 | `ALIPAY_APP_ID` | 已上线且获支付权限的应用 AppID |
| 支付宝 | `ALIPAY_SELLER_ID` | 实际收款支付宝账户的卖家 ID／PID |
| 支付宝 | `ALIPAY_PRIVATE_KEY_PATH` | 上传应用公钥所对应的应用私钥 PEM 路径 |
| 支付宝 | `ALIPAY_PUBLIC_KEY_PATH` | 支付宝公钥 PEM 路径，不能填应用公钥 |

检查参数准备完成后再切换 `PAYMENTS_MODE=merchant`；配置 `PUBLIC_BASE_URL=https://你的实际域名`、`PRO_PRICE_FEN=1990`、`INLINE_WORKER=0`。Teacher 保持原有购买开关关闭。Windows 路径可填 `C:/essay-grading/secrets/wechat-private.pem` 等实际路径；环境变量中的路径不加额外引号。Docker 使用 `deploy/compose.payments.yaml` 中的挂载路径。

支付宝正式网关为 `https://openapi.alipay.com/gateway.do`；沙箱使用单独的沙箱账户、应用与密钥，沙箱成功不代表正式产品权限已经获批。

回调地址由程序下单时传入：

- 微信：`https://你的实际域名/api/payments/wechat/notify`
- 支付宝：`https://你的实际域名/api/payments/alipay/notify`

域名必须可从公网以 HTTPS 访问并转发到实际应用。之前部署记录中存在备案拦截，该记录不能说明现在的连通性；切换前需重新检查。不要根据浏览器跳转开通会员。

## 本地参数检查

在项目根目录运行：

```powershell
.venv\Scripts\python scripts/check_payment_config.py
# 只检查一个渠道：
.venv\Scripts\python scripts/check_payment_config.py --channel wechat
```

工具只输出字段是否已配置、RSA PEM 是否可读取、基础设置是否满足要求，不显示密钥或账号值，不创建订单、不访问数据库、不请求支付平台。它仅检查当前普通商户适配，不能判断服务商模式、账号权限、证书与商户的关联或公网回调连通性。

完成参数准备及接口类型确认后，重启 web 和独立 worker，进行受控的真实支付、重复通知、主动查单与退款验证，核对实际到账记录和订阅来源。尚未进行这些验证前，保持真实支付联调状态为待执行。

## 官方参考

- 微信普通商户 Native：https://pay.wechatpay.cn/doc/v3/merchant/4012791877
- 微信小微商户进件：https://pay.wechatpay.cn/doc/v3/partner/4012722249
- 微信合作伙伴接入：https://pay.wechatpay.cn/doc/v3/partner/4012062375
- 支付宝扫码支付接入：https://developer.alibaba.com/docs/doc.htm?articleId=105170&docType=1&treeId=292
