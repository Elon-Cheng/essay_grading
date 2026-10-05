# Paypro 本机购买系统

本目录由墨评 `scripts/setup_paypro_local.py` 从用户提供的高级版生成，独立于原源码和墨评现有运行配置。随机共享密钥已同时写入 `.env` 和 `essay.env`，勿将这两个文件上传至仓库或发送到聊天。

## 启动

安装并启动 Docker Desktop，使用 Linux 容器。在本目录执行：

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 paypro
```

浏览器访问 `http://localhost:8889`。首次启动需要下载镜像、编译 Java 和初始化专用数据库。MySQL、Redis 不映射主机端口，网页仅监听本机。

生成配置已关闭各收款渠道、关闭金额递减，并在源码副本应用签名日志清理和支付宝通知验签补丁。启动使用 JAR，不使用原版附带的远程监控启动参数。生成目录不代表服务已经启动；请用 `docker compose ps` 确认运行状态。

## 配置自己的收款

编辑 `config/application-prod.yml` 填写 `alipayDmfAppId`、`alipayDmfAppPrivateKey` 和 `alipayDmfPublicKey`；支付宝公钥须来自支付宝平台。微信需将自己的 19.90 元收款码放在 `qr/wechat/19.90/1.png`，并配置高级版所需的微信到账辅助程序。没有随目录复制作者的演示收款码。

在 `.env` 填写邮箱服务及授权码、收款人和联系邮箱。当前 SMTP 配置使用 587 / STARTTLS；如使用 465，需同步调整 YAML 的协议、SSL 和 STARTTLS。本机生成时已替换演示管理员密码，账号和随机密码见 `admin-access.txt`，后台地址为 `http://localhost:8889/admin/login.html`。

确认参数后，将对应 `payMethods` 项目的 `status` 改为 `true`，运行 `docker compose restart paypro`。

## 与墨评联调

`essay.env` 是待合并的支付配置，不会自动覆盖墨评 `.env`。墨评当前适配要求 HTTPS 和已验证到账，本机 HTTP 页面只能用于启动和页面配置检查，尚不能完成端到端会员购买。

完整联调需要 Paypro 与墨评均有可访问的 HTTPS 地址；将 `.env` 中 `PAYPRO_PUBLIC_URL`、`essay.env` 中 `PAYPRO_BASE_URL` 改为支付地址，并在墨评设置 `PUBLIC_BASE_URL`。两个系统共享密钥保持相同。支付宝回调为 `支付地址/alipay/notify`，会员通知为 `墨评地址/api/payments/paypro/notify`。

分别核实真实到账、金额、重复通知只发一次会员，再设置墨评对应 `PAYPRO_ALIPAY_ENABLED=1` / `PAYPRO_WECHAT_ENABLED=1` 和 `PAYPRO_SETTLEMENT_VERIFIED=1`。先本机配置阶段保持这些开关为 0。

数据库 SQL 仅在专用空数据卷首次初始化时执行。日常停止用 `docker compose down`，保留数据卷。Java 构建、服务启动、真实收款及微信辅助程序仍待运行验证。
