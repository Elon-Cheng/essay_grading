# 支付接入残留清理记录

2026-10-05，按用户要求清理已取消的 PayPro 和未采用的 WeChatDeveloper 接入残留。

## 已清理

- 本地 `output/paypro-local`、`output/paypro-native`、`output/paypro-source`、`output/WeChatDeveloper-review`，5 份重复的 credit-deploy 暂存目录和 11 个临时诊断/安装脚本。合计约 0.96 GiB。
- 本地 3 个 `essay-paypro-local-*` Docker 容器以及 `essay-paypro-local-paypro`、`essay-paypro-server` 两个项目镜像。未执行全局 Docker 清理。
- 服务器 `C:\paypro` 废弃运行目录及 `PayPro-web`、`PayPro-redis`、`PayPro-database` 三个计划任务。
- 服务器作文网站 `.env` 中的 PayPro 专用配置项；原配置另存恢复副本。原 Caddy 配置没有支付域名或 8889 代理，无需修改。

## 保留

- 作文、用户、订单、批改次数以及批改历史数据；网站现有支付代码和数据库表仍保留，避免破坏现有页面和历史记录。
- Docker 数据卷和对应本地恢复配置：`output/payment-cleanup-20261005T122454`。
- 原部署前快照 `output/credit-server-before` 和一份成功部署包 `output/credit-deploy-20261005T030401Z`。
- 服务器完整 PayPro 数据目录、Redis 数据、配置、密钥和恢复用 JAR：`C:\essay-grading\backups\payment-cleanup-20261005T042746Z\retired-paypro-data`。副本经逐文件 SHA256 核对后才删除运行目录。数据库正常关闭命令失败，因此停止其进程后保留了完整数据和恢复文件；尚未执行恢复演练。
- 用户原始提供的源码目录 `F:\BaiduNetdiskDownload\paypro-高级版` 未修改或删除。

## 验证

清理完成后，网站 `/healthz` 返回 HTTP 200，`/api/payment/products` 的支付宝和微信购买渠道均关闭。没有重启或删除作文批改 worker。服务器 C 盘可用空间为 1,531,269,120 字节（约 1.43 GiB）。本地没有遗留 Docker 容器，三个 PayPro 数据卷仍保留。

PayPro 部署文档已标记为历史记录，避免按过时说明重新启用服务。
