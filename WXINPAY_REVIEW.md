# wxinpay 接入检查

检查日期：2026-10-03。
仓库：https://github.com/wxinpay/wxinpay
检查提交：`e33bc0f6190309270d641dabb3e682ead4b37949`。
本地源码：`output/wxinpay-source`，未运行第三方 PHP 代码，未部署至生产。

## 当前结论

该公开仓库不足以实现个人收款码到账监听和自动发放订阅。暂不能完成 wxinpay 自动收款接入；生产继续使用现有个人收款码、付款凭证及管理员核实到账流程。

## 已核实的缺项

本次重新下载远端 HEAD，与本地留存源码提交一致。以下为固定提交的源码位置，便于取得完整版本后逐项核对：

- [下单代码](https://github.com/wxinpay/wxinpay/blob/e33bc0f6190309270d641dabb3e682ead4b37949/wxinpay_inster.php)：数据库占位符、SQL 拼接和多余的等号。
- [用户提交付款状态](https://github.com/wxinpay/wxinpay/blob/e33bc0f6190309270d641dabb3e682ead4b37949/wxinpay_userPush.php)：`wxSure=2` 分支仅查询记录，没有到账核验或支付成功通知。
- [sql 目录中的文件](https://github.com/wxinpay/wxinpay/blob/e33bc0f6190309270d641dabb3e682ead4b37949/sql/index.html)：内容为 HTML 表单，不是建表 SQL。

- 未提供到账监听程序、可信到账数据来源、支付回调签名或查单协议。
- `sql` 目录仅有示例 HTML 表单，没有数据库建表脚本。
- `wxinpay_inster.php` 存在多余的 `=`，数据库连接、表名和字段名仍为占位内容；多处直接拼接请求参数构造 SQL。
- `wxinpay_userPush.php` 接受用户提交的 `wxSure=2`，但未实现到账核验、订单支付更新或可信回调；还引用了仓库不存在的 `phpmailer/functions.php`。
- 示例页面提交到不存在的 `insert.php`，无法构成可运行的支付流程。

## 继续接入所需信息

需要完整可运行的 wxinpay 服务端与到账监听端，或真实部署实例的接口文档，至少包含下单、查单、到账回调字段、签名验证和唯一交易号。取得这些信息后，才能把可信支付结果接入现有订单结算事务，校验订单金额、渠道和交易号，并保证重复通知只发放一次会员。

不能仅凭用户点击“已付款”、上传截图，或未经验证的外部请求自动发放订阅。
