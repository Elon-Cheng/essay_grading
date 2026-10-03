# Jamjams 节点看门狗

已核对本机 Jamjams 前端实际使用的 WebSocket IPC：
`ws://127.0.0.1:15734/ipc`，消息包含 cid/type/method/params。
`getState` 已实际只读调用通过，检测到六个节点和 1080 代理。
`checkStatus(server_id)` 和 `changeServer(server_id)` 来自同版本前端源码。
这是客户端内部接口，版本更新后需要重新执行兼容性检查。

2026-10-03 已通过项目已有 DPAPI 加密部署凭据发布至 123.57.106.87。
服务器同样使用 15734 IPC、1080 代理和六个节点，getState/所有节点 checkStatus 实测通过。
已有 JamjamsStartup 使用 Administrator 的 Password 开机任务，在 Session 0 运行。
新看门狗任务 EssayGradingJamjamsWatchdog 使用 SYSTEM 开机启动，已经启动并实际通过代理探测。
已开启 Jamjams 的 connectOnStart 和代理连接；原值备份在服务器
`C:/essay-grading/backups/jamjams-settings-20261003-203012.json`。
原脚本备份目录：`C:/essay-grading/backups/jamjams-watchdog-20261003-203011`。
六个节点在线，当前节点保持不变；故障切换采用本地模拟测试，未人为断网。
本次仅安装节点控制，不修改作文应用的 AI 路由、不重启 web/worker。

## 安装到服务器

将包内的 scripts/ 和 deploy/ 文件合并到 `C:/essay-grading`，用运行 Jamjams 的同一个 Windows 账号执行：

```powershell
Set-Location -LiteralPath C:\essay-grading
.venv\Scripts\python.exe -m pip install 'httpx>=0.27' 'websockets>=15'
.venv\Scripts\python.exe scripts/jamjams_watchdog.py --inspect
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\install-jamjams-watchdog.ps1
```

先核对 inspect 成功、节点数量符合预期。若 IPC 端口不同，两个命令都加
`--ipc-url ws://127.0.0.1:实际端口/ipc`（Python）或
`-IpcUrl ws://127.0.0.1:实际端口/ipc`（PowerShell）。

## 行为

- 安装后立即启动；此后同一账号每次登录自动运行隐藏的监控进程。
- Jamjams 未启动时每 5 秒检查一次；启动后自动开始节点检测，关闭后回到等待状态。
- 默认每 30 秒通过本机 HTTP CONNECT 代理访问 SU8 模型列表，不发送 API 密钥或生成请求。
- 连续三次网络故障后检查其他节点，跳过离线节点；切换候选节点后再次验证目标访问。
- 成功切换后保持该节点，不为低延迟抢换节点；切换冷却 5 分钟。
- 候选不可用则回到原节点继续寻找；一轮全部失败后冷却，避免反复试切。
- 已收到 HTTP 403、429、5xx 时记录为上游 HTTP 状态，不将其直接当成节点故障。
- 用户关闭代理或退出账户后暂停，不自动登录、不强制开启代理；用户手动切点会重置失败计数并进入冷却。
- 日志最多约 4 MB，不记录节点凭据、订阅链接、账户 UUID 或后台错误原文。

SU8 是当前项目使用的 AI 入口；短请求成功不代表完整 SSE 生成可靠。
脚本只控制 Jamjams；项目是否使用代理还需配置并验证 AI_PROXY_URL。
切换可能影响正在进行的长连接，不能无缝迁移已发出的生成请求。

此安装使用登录任务加进程监控实现“跟随启动”，不是修改 Jamjams 本身。
服务器已有开机运行的 JamjamsStartup 任务时，可给安装命令追加 `-SystemStartup`，
将看门狗作为 SYSTEM 开机任务运行，通过本机 IPC 控制已有 Jamjams，无需新增登录密码。
此时看门狗不依赖交互登录，但 Jamjams 本身是否无人登录运行仍由其启动任务决定。
远程桌面断开通常保留会话，但注销会结束交互账号进程；本方案不承诺注销后继续运行。
若需真正无用户登录运行，应另用支持 Windows 服务的代理内核。

## 查看及停用

```powershell
Get-ScheduledTask -TaskName EssayGradingJamjamsWatchdog
Get-Content C:\essay-grading\logs\jamjams-watchdog.log -Tail 30
Stop-ScheduledTask -TaskName EssayGradingJamjamsWatchdog
Disable-ScheduledTask -TaskName EssayGradingJamjamsWatchdog
```

停止或停用任务不关闭 Jamjams，不修改其当前节点。任务采用 IgnoreNew，避免重复登录启动同一计划任务实例。
正式安装后用可控断网验证阈值和恢复；本地测试只模拟故障，没有切换用户正在使用的节点。
