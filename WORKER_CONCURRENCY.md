# 作文批改并发

独立 `worker.py` 支持 `WORKER_CONCURRENCY=1..8`，默认 1。现有服务器按用户要求配置 8：同一 worker 进程最多并行处理八篇作文，剩余任务保存在数据库队列中。此配置只控制独立 worker，不改变网站的 INLINE_WORKER 行为。

每篇作文保持独立目录、ContextVar 调用记录、任务租约及额度结算。任务领取和额度更新仍经过数据库事务锁；锁只覆盖短事务，不覆盖 AI 请求。支付查单和租约恢复使用独立维护线程，每 30 秒调度一次，避免支付网络请求阻塞批改调度。

修改服务器 `C:\essay-grading\.env` 中的 `WORKER_CONCURRENCY` 后，需在没有正在批改的任务时重启 `EssayGradingWorker`。不要直接强制结束正在执行的 worker。正常 SIGTERM/SIGINT 会停止领取新任务并等待当前线程完成；Windows 计划任务强制结束不提供此保证。

`USER_MAX_PENDING` 是每个用户排队和运行中的任务数限制，与全站批改并发数不同，保持原配置。提高批改并发前需确认 AI 服务的同时请求限制、服务器内存及预算。单篇作文的多个批改阶段仍按原流程执行，不因本修改而同时发出该篇的所有 AI 请求。

验证：`python -m unittest tests.test_worker_concurrency.WorkerConcurrencyTests tests.test_worker_concurrency.WorkerClaimTests`。测试使用模拟 AI 输出，不产生真实 AI 费用；上线后仍需观察真实请求限流和失败率。
