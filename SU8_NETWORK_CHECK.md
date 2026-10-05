# Jamjams / SU8 本机连接检查

2026-10-03 后续服务器检查及已发布优化见 [NETWORK_STABILITY.md](NETWORK_STABILITY.md)。以下保留此前本机检查记录。

检查日期：2026-10-03（北京时间）。

本次未复现断流。Jamjams 进程运行，监听 127.0.0.1:1080，实测支持 HTTP CONNECT 和 SOCKS5。Windows 系统代理为 socks=127.0.0.1:1080；检查进程继承了指向该端口的 HTTP_PROXY 和 HTTPS_PROXY。Jamjams 日志未开启，无法追溯历史故障。

对 https://www.su8.codes/v1/models 进行无密钥请求，最终一轮结果如下。401 表示传输连通且进入鉴权流程，不表示模型生成成功。

| 路径 | 预期 401 次数 | 中位耗时 |
| --- | --- | --- |
| 直连 | 10/10 | 0.885 秒 |
| HTTP 代理 | 10/10 | 0.956 秒 |
| SOCKS5 代理（代理端解析域名） | 10/10 | 0.939 秒 |
| 继承环境变量，加载新增 NO_PROXY | 10/10 | 0.894 秒 |

已添加的本机设置：

- 用户环境变量 NO_PROXY：localhost,127.0.0.1,::1,www.su8.codes。
- Windows 当前用户 Internet Settings 的 ProxyOverride 保留原值，并追加 www.su8.codes。
- 原设置备份：`C:\Users\Cheng Yilong\AppData\Local\Jamjams\network-backups\su8-20261003-134502.json`。

在独立测试进程中将 HTTPS_PROXY 临时设为不可用的 127.0.0.1:1，加载新增 NO_PROXY 后，httpx 请求仍返回 401（2.292 秒），验证 SU8 可绕过代理。没有修改运行中的 Jamjams 配置、切换节点或重启客户端。

已运行的应用不会自动继承新的环境变量，需要完全退出并重开相应客户端。启动脚本若覆盖 NO_PROXY，仍需在该脚本中保留 www.su8.codes。Jamjams 重连也可能重写 Windows 代理例外，应届时检查。显式忽略系统例外/环境变量的客户端不受此设置控制。

复测命令（PowerShell，项目目录）：

```powershell
$env:NO_PROXY = [Environment]::GetEnvironmentVariable('NO_PROXY', 'User')
.venv\Scripts\python.exe scripts/check_su8_network.py --count 10
```

脚本不读取密钥，不发送生成请求。HTTP 和 SOCKS 测试显式清除 NO_PROXY，确保确实经过代理。

如需回滚本次本机设置（如之后又修改过设置，请先核对备份）：

```powershell
$saved = Get-Content -Raw -LiteralPath "$env:LOCALAPPDATA\Jamjams\network-backups\su8-20261003-134502.json" | ConvertFrom-Json
[Environment]::SetEnvironmentVariable('NO_PROXY', $saved.UserNoProxy, 'User')
Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyOverride -Value $saved.ProxyOverride
```

局限和后续定位：本地项目没有 .env，当前进程没有 OPENAI_API_KEY，因此未验证鉴权、流式长连接或真实批改。部署文档记录的服务器生成超时不能归因于本机 Jamjams，本次本机设置也不改变服务器配置。

项目 app.py 使用非流式 Responses 请求。SU8 官方[排障文档](https://www.su8.codes/docs/troubleshooting)将长时间非流式请求列为 502/504 的常见原因，建议流式输出。这与长批改故障存在可能关联，但需要实际响应状态、耗时和请求 ID 佐证。本次未在缺乏鉴权验收条件下变更生产请求协议或扩大自动重试。
