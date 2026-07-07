## Why

真实 Claude 诊断任务在数据源 schema 不完整或表名猜错时会反复调用工具，直到触发 `AGENT_MAX_TURNS`，最终 job 进入重试但缺少完整工具调用记录，排障只能从平台日志倒推。当前 Agent 也拿不到真实数据库 schema 目录，只能根据自然语言猜业务表，导致“缺少证据”被误处理成继续试错。

## What Changes

- 失败时也持久化真实 Claude 运行期间已经发生的工具调用摘要，避免 max turns、timeout、SDK 错误等失败路径丢失诊断证据。
- Internal API Platform 提供面向 Agent 的只读 schema 目录能力，按 environment/base/workshop 返回允许访问的表、列和必要元数据，不暴露连接密钥。
- Agent 上下文和提示策略使用 schema 目录约束 SQL 诊断，要求模型只查询目录中存在且属于目标 workshop 的表和列。
- 当平台返回表不存在、字段不足、策略拒绝、空 schema 或缺少关键证据时，Agent 必须停止扩散式试错，并产出“不具备诊断证据”的安全报告。
- 对 max-turns exhaustion 的错误分类和 debug API 观测做收敛：这类确定性工具循环不应被无限当作瞬时失败重复消耗。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `claude-agent-runtime-integration`: 真实 Claude SDK 工具循环在失败路径也必须返回或持久化安全工具事件，并区分工具循环耗尽与瞬时 SDK 故障。
- `claude-diagnostic-runtime`: 诊断上下文必须包含可用 schema 目录，最终报告策略必须在缺少证据时停止试错并明确不确定性。
- `readonly-tool-platform`: Internal API Platform 必须提供按拓扑和权限过滤的只读 schema 目录，并将表/字段不存在类错误表达为模型可理解的安全结果。
- `agent-job-debug-api`: 调试 API 查询 tool calls 时必须能看到失败前已经发生的真实运行时工具调用摘要。

## Impact

- 影响 `backend/app/modules/agent/infrastructure/claude_code_agent_client.py`：工具事件缓冲、失败时事件携带或持久化、max-turns 错误映射。
- 影响 `backend/app/modules/agent/application/agent_executor.py`：失败路径保存已收集工具事件，并记录可审计 step。
- 影响 `backend/app/modules/agent/application/agent_context_builder.py` 和诊断 prompt/skill 注入：引入 schema 目录和停止试错规则。
- 影响 `backend/app/modules/internal_api_platform/`：新增 schema 目录查询服务、HTTP endpoint、权限/拓扑过滤和安全摘要。
- 影响 `backend/app/modules/internal_tools/`：新增或扩展内部工具客户端契约，把 schema 目录传给 Agent。
- 影响测试：fake SDK 失败路径、max-turns 分类、schema 目录 endpoint、缺证据报告、debug API tool-calls 可见性。
