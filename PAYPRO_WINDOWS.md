# PayPro 支付宝：现有 Windows 服务器部署

> 2026-10-05：用户已取消此部署路线并要求清理残留。下文为原部署说明，不再是启用指引。

服务器：123.57.106.87。独立目录：`C:\paypro`。准备的公网地址：`https://pay.english-essay-grading.online`。

## 已安装与连接

- PayPro Java 服务、独立 MariaDB 数据库、Redis 缓存，计划任务 `PayPro-web`、`PayPro-database`、`PayPro-redis` 管理启动与失败重启。
- 三个端口只监听本机：8889、3307、6380。作文服务仍使用自己的数据库与运行目录。
- 本站与 PayPro 的共享签名密钥已由程序生成并同步至服务器配置，不在聊天或仓库显示。
- 支付宝 OpenAPI 控制器补齐；同一订单直接生成支付宝原生二维码，本站通过受登录保护的接口显示二维码。
- 回调验签后再查询支付宝，核对订单号和金额；本站成功确认回调后，PayPro 才将订单标为完成。确认失败保留待支付订单，定时重试有效期内的订单。
- 可选邮件通知不配置时跳过，不作为支付宝自动收款的必需条件。

准备脚本：`scripts/prepare_paypro_alipay.py`，只应用于隔离的源码副本。当前构建使用已运行版本的依赖，在 Java 8 中编译补丁并保留原 Spring Boot JAR 的依赖条目。

## 仍需填写

1. DNS 添加 A 记录：主机名 `pay`，记录值 `123.57.106.87`。
2. 支付宝应用私钥放入 `C:\paypro\secrets\alipay-app-private-key.pem`。
3. 支付宝公钥放入 `C:\paypro\secrets\alipay-public-key.pem`。这是支付宝平台公钥，不是应用公钥。
4. AppID 写入 `C:\paypro\settings.json` 的 `ALIPAY_APP_ID`，或传给配置脚本的 `-AppId` 参数。密钥也可直接保存在该受保护配置文件中。

填写后在服务器执行：

```powershell
powershell -NoProfile -File C:\paypro\configure-paypro-alipay.ps1 -AppId YOUR_APP_ID
powershell -NoProfile -File C:\paypro\activate-paypro-proxy.ps1
```

配置脚本读取密钥文件，不回显密钥。HTTPS 脚本先检查 DNS 指向，再备份、验证并热加载 Caddy 配置。

## 验证与开放

支付宝回调为 `https://pay.english-essay-grading.online/alipay/notify`；PayPro 通知本站为 `https://english-essay-grading.online/api/payment/callback`。

密钥及 HTTPS 就绪后，`configure-paypro-alipay.ps1 -EnableForVerification` 可打开支付服务的支付宝入口进行受控验收；本站的公开购买开关仍保持关闭。需核实支付宝真实到账、正确金额、本站只增加一次次数，以及重复通知不重复入账。验收完成后，再设置作文服务器 `.env` 中 `PAYPRO_ALIPAY_ENABLED=1`、`PAYPRO_SETTLEMENT_VERIFIED=1` 并重启作文服务。微信维持关闭。

原有 `PAYMENTS_MODE` 保留，用于既有会员订单兼容；新增按次购买使用独立接口，不将用户的次数订单转为订阅。

后台地址：`https://pay.english-essay-grading.online/admin/login.html`。随机管理员账号配置在 `C:\paypro\admin-access.txt`，只在服务器读取，不复制到聊天。默认收款渠道关闭。

## 依赖来源

- [MariaDB 官方 Windows ZIP 部署说明](https://mariadb.com/docs/server/server-management/install-and-upgrade-mariadb/installing-mariadb/binary-packages/installing-mariadb-windows-zip-packages)
- [Adoptium 官方下载 API](https://api.adoptium.net/v3/assets/latest/8/hotspot?architecture=x64&image_type=jre&os=windows&vendor=eclipse)
- [Redis Windows 移植版发行页](https://github.com/tporadowski/redis/releases/tag/v5.0.14.1)

Java、MariaDB 压缩包按官方 SHA256 校验；Redis 取自维护者 HTTPS 发行资产，并记录校验值。该 Redis 是 Windows 移植版，配置为本机监听及独立密码。
