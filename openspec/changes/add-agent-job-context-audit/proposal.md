## Why

当前 `one_runtime` 已有安全的 Job 执行汇总、模型轮次和失败阶段，但它按既有安全边界明确排除了 Prompt、完整模型回复、raw SDK message 和原始工具载荷，仍无法分析某个 Job 实际发送给模型的上下文构成及增长过程。用户已明确要求：在受授权的 Job 详情中保存并展示完整、未脱敏的 Prompt、文件/会话上下文、模型可见工具结果和模型原始响应，以支持后续调优。

## What Changes

- 新增按 Runtime invocation 固化的完整 Job 上下文审计，保存应用装配 Prompt、来源清单、SDK 原始消息、Messages API 原始 request/response、完整模型可见工具输入输出和 usage 摘要。
- 在 Python Runtime 内采集原始数据，通过新的 Runtime protocol `1.5` 分块传给 Worker；不恢复已被 Provider/Claude Code 隐藏的 reasoning，也不主动复制 Runtime Credential 或认证 Header。
- 新增 expand migration `124` 保存不可变 invocation 审计；不向 `agent_job` 追加可重算统计列，并继续复用现有 `agent_job_execution_summary`。
- 成功、失败、超时和重试都保存已经产生的审计；相同 invocation 重放必须幂等，历史 Job 不回填。
- 完整正文只在通过 `jobs.read` 和现有业务范围检查后，由管理端 Job 详情返回；Debug evidence、Tool Call、MCP 审计继续保持安全摘要。
- 明确修订既有“不得保存完整 Prompt/原始响应”边界：完整正文只允许进入 Runtime v1.5 的 `agent_run_audit` 专用链和授权后的 Job 详情；普通 RabbitMQ、Job 快照、日志、归一化事件、Debug/Tool/MCP 主账仍不得保存或返回完整正文，Credential、认证 Header、Cookie 和 private thinking 继续绝对禁止。
- 去除模型可见会话重复：当前 Job 输入只作为 User Prompt 发送一次，历史上下文排除当前输入；滚动摘要与最近历史消息只渲染一份，`retrieved_context` 仅保留会话截断和计数元数据。
- 去除上下文审计自身的重复存储：每个来源只保存规范化 `content`、字符数、Token 估算和截断事实，页面按需渲染，不再持久化可由 `content` 确定性生成的 `rendered_text` 副本。
- 优化 Agent 运行详情：先显示上下文、模型请求、峰值/累计 Token、缓存、成本，以及注册/实际加载/实际调用/自动批准工具数等调优摘要；再将上下文、模型请求/响应、工具原文和 usage/元数据默认折叠，长内容可滚动查看。
- **BREAKING**：Runtime protocol 从 `1.4` 升级为 `1.5`；Worker 必须先支持新协议，再切换 Runtime/Publication。

## Capabilities

### Modified Capabilities

- `execution-delivery`: 定义完整 invocation 审计的采集、分块传输、持久化、授权查询与折叠展示，将其纳入成功、失败、超时、重试和 Runtime 恢复链路，同时保持执行、工具、MCP 与 Delivery 事实边界；不新增第 11 个 canonical capability。

## Impact

- Runtime contract：新增 v1.5 `audit_chunk` 事件和完整性元数据。
- Python Runtime：增加无应用层脱敏/截断的审计采集和 OTel raw API body 文件读取。
- Worker/数据库：新增审计重组、幂等落库和管理端受控读取；新增 migration 124。
- Web：扩展 operations schema/API/详情页面与长内容回归测试。
- 容量与安全：详情响应和数据库将包含企业正文；授权仍为 `jobs.read` 加业务范围，运行凭据、认证 Header、Cookie 和 private thinking 不进入审计；上下文来源不保存可派生的重复渲染副本。
