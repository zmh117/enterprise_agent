## Why

当前运行记录无法把 Job 冻结工具、受 Job Principal 约束的 MCP 实际声明、Runtime 真正交给 SDK 的有效工具以及 Prompt 的工具声明放在同一事实链中，导致 Mac 与 Windows 部署出现差异时只能依赖模型自述猜测。系统需要在模型调用前形成可验证、可审计且不含完整 Prompt、原始 MCP 载荷或凭据的工具契约证据，并在关键缺失或 Schema 不一致时失败关闭。

## What Changes

- 按 `Job + invocation_id + request_digest` 保存不可变工具契约观测，关联既有 Job MCP Tool Snapshot，并分别记录冻结工具、File MCP 受控 `tools/list` 观测、Runtime 有效工具和 Prompt 工具声明。
- 为每个工具记录安全标识、Server、来源（冻结 MCP、Runtime 派生或 SDK 内置）、Schema hash、各层存在性和稳定对账状态；不保存完整 Schema、描述、Prompt、业务正文、URL、Header、Token 或原始 MCP/SDK 载荷。
- Runtime 在模型调用前验证冻结工具与 File MCP 声明、Runtime 有效工具和 Prompt 声明；缺少必需工具、Schema 不一致、未授权工具进入有效集合或 Prompt 宣称不存在的可调用工具时失败关闭。File MCP 额外但未冻结的工具不暴露，只记录为已忽略。
- 将 `select_sandbox_output` 等代码注册工具明确标记为 `runtime_derived`，不得因其不在 Job MCP Snapshot 或远端 File Service 中而误报漂移。
- 为 Control Plane/Worker、Python Runtime 和 File Service 记录构建身份，包括组件、源码 revision、build ID、平台以及部署可提供时的镜像 digest；跨架构一致性以源码 revision 和契约 hash 为主，镜像 digest 只作为实际产物证据。
- 为系统 Prompt 增加不含动态业务内容的模板版本和契约 hash，并由 Runtime 有效工具事实生成可调用工具声明。
- 运行记录列表展示 `MATCH`、`DRIFT` 或 `NOT_OBSERVED` 汇总状态；Job 详情按 invocation 展示构建身份、冻结工具、远端观测、Runtime 有效工具、Prompt 契约及逐工具对账矩阵。
- **BREAKING**：执行协议从 Runtime protocol 1.3 升级到 1.4；Worker、Python Runtime、合同生成代码、golden fixtures、健康声明、恢复路径和受影响 Publication 必须整体迁移，不保留新旧 Runtime 镜像并行消费路径。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `execution-delivery`：新增 invocation 级工具契约证据、Runtime 1.4、模型调用前漂移校验、安全运行记录投影和 Prompt 契约来源要求。
- `platform-operations`：新增多组件构建身份注入、部署一致性验证和跨平台镜像证据口径。

## Impact

- Runtime 合同：`contracts/agent-runtime` schema、errors、limits、golden fixtures 和生成代码升级到 1.4。
- 后端：Job MCP Tool Snapshot 安全投影、Runtime 请求/事件、File MCP bridge 远端声明核对、契约状态计算、构建身份注入、运行记录 API 和持久化查询。
- 前端：运行记录列表状态和 Job 详情工具契约矩阵。
- 部署：相关服务以同一源码 revision/build ID 重建；本地多架构镜像允许 digest 不同但必须报告平台和契约身份。
- 测试：协议合同、权限与脱敏、File bridge、失败关闭、重试 invocation、API/UI、Compose 构建身份和 Mac/Windows 可比性回归。
