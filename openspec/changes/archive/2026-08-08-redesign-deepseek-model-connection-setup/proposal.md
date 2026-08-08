## Why

当前 Agent Profile 把模型连接配置、API Key 轮换和连接测试拆成三个独立步骤；保存连接后页面仍可能使用旧 revision 提交 Key，造成 409 并发冲突，而且管理员必须先猜测模型名，无法从 DeepSeek 获取当前可用模型。现在需要把首次配置和后续重配收敛为一个可验证、可发现模型、最终原子保存的连续流程。

## What Changes

- 新增仅面向 DeepSeek 官方服务的模型连接配置向导：输入 Anthropic Base URL 与 API Key 后，先验证凭据并从同一官方服务的 `GET /models` 获取可用模型。
- 使用发现结果配置主模型、Opus/Sonnet/Haiku 默认模型和子 Agent 模型；空的默认映射继续继承主模型。
- 在保存前通过当前 Claude Agent SDK 兼容路径测试所选主模型，且最终保存时由服务端再次验证同一配置，避免仅依赖前端状态。
- 将非敏感连接 revision 与 encrypted DB Secret 的创建或轮换合并为一个乐观并发、数据库原子的配置操作，消除“先保存连接、再轮换 Key”造成的 revision 竞态。
- 已有可用 Credential 可以继续使用且不回显明文；缺失、停用或需要轮换时必须输入新 Key。
- 探测或测试失败不得创建连接 revision、Secret 或活动版本；API Key 不进入日志、审计、查询响应、前端查询缓存或模型列表结果。
- 为鉴权失败、模型发现失败、模型列表为空、模型不可用、Claude SDK 测试失败、超时和 revision 冲突提供稳定中文错误。
- **BREAKING**：Agent Profile 不再提供独立的“保存连接版本 → 配置/轮换 API Key → 测试已保存版本”管理流程；前端改用统一向导和原子配置 API，不保留旧交互兼容。
- 不增加任意第三方 Anthropic-compatible Provider、独立模型发现 URL、OpenAI Runtime Adapter、HTTP Provider 插件或自动 Agent 发布。

## Capabilities

### New Capabilities

- `deepseek-model-connection-setup`: 规定 DeepSeek 官方 Anthropic 连接的凭据探测、模型发现、模型映射、Claude SDK 测试、原子保存、Secret 生命周期和管理 Web 流程。

### Modified Capabilities

无。

## Impact

- 后端模型连接模块：新增 DeepSeek 探测/模型发现端口、临时测试输入和原子配置服务，调整 revision 与 Secret 的事务边界。
- 管理 API：新增模型发现、临时配置测试和原子保存契约，并停止前端使用独立 revision/credential/test 三段式接口。
- Agent Profile Web：把连接表单和 Key 弹窗改为单页分步向导，模型字段改为发现结果驱动的选择控件。
- 安全与网络：继续复用 RBAC、审计、SSRF/DNS/redirect 防护和 encrypted DB Secret Provider；外部目标严格限定为 DeepSeek 官方 HTTPS 主机。
- 测试与运维：增加并发、无副作用失败、Secret 恢复、模型发现响应校验、真实 SDK 测试和容器端到端验证。
- 依赖关系：本变更建立在 `add-agent-profile-model-connection-management` 已有模型连接、Agent Publication 和 Claude Agent SDK Runtime 能力之上，不重写历史 Publication。
