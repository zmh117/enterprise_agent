# Design

## Context

管理端的取消操作要求 `jobs.manage`。插件提问会产生关联应用、发起人与 Job 的消息回执，已有回答读取接口会核对回执、会话与渠道。Worker 和 Runtime 已支持持久化取消意图。

## Goals / Non-Goals

本次把本人取消权限限定在浏览器扩展协议 v1。管理端继续使用现有的管理授权；插件用户只提交 Job 标识，服务端决定执行实例。

## Decisions

1. 使用 `POST /api/browser-extension/jobs/{job_id}/cancel`。复用回答读取的可见性校验，核对凭据与平台来源、当前应用授权，以及回执、会话和 Job 的用户与插件渠道归属。其他用户或渠道的任务返回 404，防止通过任务标识探测业务活动。
2. 在同一事务中检查权限、调用现有 Job 取消流程并记录操作人。取消流程先锁会话再锁 Job，权限读取沿用这个加锁顺序以避免锁升级冲突。
3. 通过 `cancelled`、`cancel_requested`、`already_terminal` 和 `outcome_unknown` 表达即时结果。只有 Job 以 `runtime_cancelled` 失败时，回答流和快照才把原因投影为「已取消」。

## Risks / Trade-offs

- 用户点击时任务可能已经完成。服务端保留先提交的终态，客户端从原回答流或快照读取结果。
- Runtime 已经准入时，返回接受请求不代表模型已经停下。API 将最终确认交给持有该次执行的 Runtime 与 Worker。

## Migration Plan

先提供 API 路由，再加载插件 0.2.8。取消状态复用现有 Job 和 Invocation 字段，无需数据库迁移。
