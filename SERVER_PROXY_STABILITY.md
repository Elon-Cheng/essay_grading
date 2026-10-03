# 服务器 Jamjams 稳定性

目标服务器：123.57.106.87，Windows，项目预计位于 C:/essay-grading。
2026-10-03 用户确认 Jamjams 和六个节点运行在服务器。当前 SSH 无可用认证，以下修改只在本地完成，尚未发布或验证服务器现状。

后续进展：已找到项目保存的 DPAPI 加密部署凭据并成功登录，完成 Jamjams 节点看门狗的服务器安装。
六个节点 checkStatus 均在线，1080 代理探测通过，SYSTEM 开机任务运行。
具体发布及备份信息见 [看门狗说明](deploy/windows/JAMJAMS_WATCHDOG.md)。
AI_PROXY_URL 的应用侧修改仍未部署，本次仅发布节点控制脚本。

## 先确认请求确实经过代理

新增 `AI_PROXY_URL`，只作用于 AI 请求，支持 HTTP CONNECT。明确设置该项时，忽略 AI_TRUST_ENV 和 NO_PROXY。空值保留原路由。不会改动支付、数据库或邮箱连接。

先在服务器确认 Jamjams 实际监听端口（不要依据本机端口推断服务器）：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 1080
```

发布新版 ai_transport.py 和 scripts/check_server_proxy.py 后，在服务器项目目录执行只读诊断：

```powershell
Set-Location -LiteralPath C:\essay-grading
.venv\Scripts\python.exe scripts/check_server_proxy.py --count 30 --interval 5 --output logs/proxy-check.json
```

同时比较直连、显式本机 HTTP 代理、.env 所指定的 AI 路由。只发送不带密钥的模型列表请求，不生成作文，不切节点。预期 401 表示短请求链路连通，不能证明长流生成成功。记录成功率、最长连续失败、延迟中位数和 P95。配置诊断不能证明当前运行的 worker 已读取新版环境变量。

对六个节点分别手动选择、执行同一测试，按持续成功率和 P95 排序，不能只按一次 ping 延迟选点。切换前确认没有活跃批改，避免影响已有流。若实际 AI 服务不是 SU8，此工具的结果不能代表该服务，需要改为它的无密钥探测地址。

## 固定主节点及备用节点

后续已发现并核对当前 Jamjams 的本地 WebSocket 控制接口，开发了专用节点看门狗：
见 [安装与行为说明](deploy/windows/JAMJAMS_WATCHDOG.md)。下文关于公开控制 API 的不确定性仍适用于其他版本；本机内部接口检查通过不代表服务器版本兼容。

建议先选最稳定的主节点，另外保留两个备用节点；其余节点用于候补。检查 Jamjams 当前版本是否提供经过验证的自动故障切换功能，其公开主页并未说明可调用的节点控制 API；不能假定可由程序自动切换。

若 Jamjams 无法实现无人值守故障切换，可使用同一服务商提供的兼容订阅部署支持服务运行的 Mihomo 内核，无需另购节点。兼容性和订阅格式必须先确认。使用 fallback 策略组，按主节点、备用节点顺序健康检查；不使用轮询或频繁追逐最低延迟。Mihomo 的 fallback 会按列表顺序选择可用节点，主节点恢复后可能重新选择主节点，不能将它视为带冷却期的粘性切换。

初始建议检测间隔 60 秒、超时 5 秒；这只是待验证参数。连续失败阈值及切换冷却若内核不支持，需额外控制器实现，不能只写几个配置项就宣称已生效。已有 SSE 连接不能迁移到另一节点，切换用于后续连接；不能保证当前生成不中断。

## 明确设置后台 worker 的路由

服务器确认 HTTP CONNECT 代理确实在 127.0.0.1:1080 监听、代理比直连更稳定后，在 C:/essay-grading/.env 设置：

```dotenv
AI_PROXY_URL=http://127.0.0.1:1080
AI_TRUST_ENV=0
AI_STREAM=1
AI_CONNECT_TIMEOUT_SECONDS=10
AI_TIMEOUT_SECONDS=180
AI_TOTAL_TIMEOUT_SECONDS=600
```

Jamjams 支持的协议需在服务器实测；如果端口只支持 SOCKS，不能套用本 HTTP 代理配置。HTTPS AI 请求使用 `http://` HTTP CONNECT 代理地址是正常用法。AI_STREAM=1 需要供应商支持 Responses SSE，现有 SU8 部署记录已有验证，其他服务不能直接套用。

此前部署记录中 AI_TRUST_ENV=0 且未设显式代理，因此后台可能直连；Windows 当前用户系统代理设置也不能证明后台 worker 使用了代理。新配置让选择可控，但不会让服务器端 Jamjams 自动启动。还需核实其开机启动、远程桌面断开及注销后代理仍可用；使用服务型内核时设置服务自动启动和故障恢复。

保存原配置与代码备份，确认无活跃批改后重启 web 和 worker，再在相同后台账号下测试。代理异常应报告连接失败，不静默转为直连重发已有生成，避免重复执行或重复计费。需要回滚时清空 AI_PROXY_URL、恢复原 AI_TRUST_ENV，并重启对应进程。

## 官方依据

- HTTPX 显式代理：https://www.python-httpx.org/advanced/proxies/
- Jamjams 官方功能：https://jamjamsapp.com/
- Mihomo fallback：https://wiki.metacubex.one/en/config/proxy-groups/fallback/

旧记录中 SU8 曾在长流中返回 server_error；代理优化无法保证修复供应商上游生成故障，应分别记录网络异常、HTTP 错误和 SSE error/request ID。
