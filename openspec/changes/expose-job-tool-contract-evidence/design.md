## Context

当前实现已经由 `agent_job_mcp_tool_snapshot` 冻结 Job 可使用的 MCP Tool 标识、Server 和输入 Schema hash，并由 Python Runtime 的进程内 File MCP bridge 根据冻结集合向 SDK 暴露工具。`select_sandbox_output` 是 bridge 按冻结的 `file_create_commit_intent` 派生的代码自有工具，不属于 File Service 的远端 MCP Tool，也不应出现在 Job MCP Snapshot 中。

目前缺少的是同一次 invocation 内的运行时对账事实：File Service 在该时刻通过 `tools/list` 实际声明了什么、bridge 和 SDK 最终暴露了什么、Prompt 把什么声明成可调用工具，以及这些组件究竟由哪个构建产物运行。因此，相同问题在 Mac 与 Windows 上只能通过模型文字回答或离散日志推断；Prompt 文字与函数 Schema 冲突时，不同模型还可能给出相反结论。

现有 Runtime protocol 1.3 使用严格 Schema，不能在不升级协议的情况下增加请求、事件和 provenance 字段。现有 `agent_runtime_event` 已按 `job_id + invocation_id + sequence` 保存不可变安全事件，运行记录 API 和管理端也已有授权边界，可以作为本变更的事实保存与展示链路。以下内容是本变更的 documented intent，不代表当前 checkout 已经具备这些运行能力。

## Goals / Non-Goals

**Goals：**

- 对每次 Runtime invocation，在首次模型调用前形成可验证的冻结、File MCP live、Runtime effective 和 Prompt declaration 四层工具事实。
- 在缺少冻结工具、输入 Schema hash 不一致、未授权工具进入有效集合或 Prompt 过度声明时失败关闭；远端额外工具只审计、不暴露。
- 保存足以比较 Mac/Windows 部署的安全构建身份，同时正确处理跨架构镜像 digest 天然不同的情况。
- 在运行记录列表和详情中提供不依赖模型自省的明确结论，并保持 Job 重试、终态恢复和历史审计可解释。
- 升级到唯一活动的 Runtime protocol 1.4，不保留 1.3/1.4 并行消费或协议协商路径。

**Non-Goals：**

- 不保存完整 Prompt、完整 MCP/SDK Schema、Tool 描述、原始 `tools/list` 响应或业务正文。
- 不把 `allowed_tools` 当成工具存在性的证据，也不通过要求模型调用破坏性工具来探测可用性。
- 不在本变更中引入通用 MCP Registry、动态 Provider 执行器或第二套 Job Tool Snapshot。
- 不要求不同 CPU 架构的镜像 digest 相同，也不让容器读取 Docker socket 来推断自身镜像。
- 不修改历史 Job、Publication 或 Runtime event；protocol 1.3 终态事实只读保留，不可恢复执行。

## Decisions

### 1. 以既有 Job Snapshot 为冻结事实，以 protocol 1.4 event 为 invocation 观测事实

继续把 `agent_job_mcp_tool_snapshot` 作为 Job 冻结 MCP Tool 的唯一事实源。Runtime protocol 1.4 新增 `tool_contract_observed` 事件；事件与 `job_id`、`invocation_id`、`request_digest`、Job Snapshot hash 绑定，并在任何首次模型请求之前产生。Worker 仍通过既有 `agent_runtime_event` 幂等保存该事件，不新增一张可与 event 漂移的完整观测表。

事件只保存以下有界字段：

- 冻结工具：`server_code`、`tool_identifier`、输入 `schema_hash` 和 Snapshot hash；
- File MCP live：远端 Tool 名、按统一算法计算的输入 Schema hash、toolset hash 和观测状态；
- Runtime effective：SDK 实际可调用名、逻辑 Tool 名、来源、Server、输入 Schema hash 和授权结果；
- Prompt declaration：模板版本、声明的可调用 Tool 名集合和 contract hash；
- 逐项稳定状态、整体状态以及参与本次事实链的组件构建身份引用。

工具输入 Schema hash 继续使用现有 `mcp_tool_schema_hash` 算法，即对 `inputSchema` 做 UTF-8、键排序、紧凑 JSON 的 SHA-256。描述、输出 Schema 或远端返回顺序不进入现有发布契约 hash，避免同一概念出现两套算法。

为运行记录列表查询增加 Job 级汇总投影，但该投影只保存状态、最后观测 invocation 和 observation hash，不复制逐工具数组。详情始终读取不可变 event 和既有 Job Snapshot。列表投影写入失败不得改变已保存 event；后台可从 event 幂等重建。

**备选方案：**新增 `job_tool_snapshot` 或为每层各建一张表。该方案查询直接，但会复制既有 Job Snapshot，并让 event、明细表和汇总表形成三套可漂移事实，因此不采用。

### 2. File bridge 在初始化后执行一次受控 `tools/list` 预检

只要 Job 冻结了 `file-service` Tool，File bridge MUST 使用当前 Job File Principal JWT 和部署固定地址建立 MCP Session，在 `initialize` 后、构造 SDK effective toolset 前调用一次 `tools/list`。分页结果必须完整收集并按 Tool 名排序；重复名称、非法名称、分页循环、超限响应或 Schema 无法规范化均视为远端契约无效。

对账规则如下：

| 条件 | 逐项状态 | 执行动作 |
|---|---|---|
| 冻结 Tool 在 File MCP live 中存在且 hash 相同 | `MATCH` | 可进入 Runtime effective 集合 |
| 冻结 Tool 缺失 | `MISSING_REMOTE` | 保存观测后、模型调用前失败关闭 |
| 同名 Tool 输入 Schema hash 不同 | `SCHEMA_MISMATCH` | 保存观测后、模型调用前失败关闭 |
| File MCP live 额外声明未冻结 Tool | `EXTRA_REMOTE_IGNORED` | 不暴露，只审计 |
| 需要 File MCP 但无法完成观测 | `REMOTE_NOT_OBSERVED` | 整体 `DRIFT` 并失败关闭 |

远端 live Tool 只有在冻结事实和当前 Job 权限均允许后才可进入 bridge。`allowed_tools` 仅代表 SDK 审批策略，不证明远端存在或已经进入 SDK effective 集合。

**备选方案：**只比较代码内 `FILE_TOOL_MANIFEST`。当前校验已经能发现 Publication 与本地代码漂移，但无法证明 Windows 容器实际连接的 File Service 镜像声明，因此不采用。

### 3. Runtime 派生工具与远端 MCP Tool 使用不同来源分类

Runtime effective 工具必须标记 `frozen_mcp`、`runtime_derived` 或 `sdk_builtin` 来源，并保存 SDK 最终使用的完整可调用名。`select_sandbox_output` 保持现有条件：仅当 Job 冻结 `file_create_commit_intent` 且输出格式策略允许时注册；其来源固定为 `runtime_derived`，其 Schema hash 来自 Runtime 代码注册定义。

派生工具无需出现在 Job Snapshot 或 File MCP `tools/list` 中，但必须能追溯到其授权前提；前提不满足却进入 effective 集合时按 `UNAUTHORIZED_EFFECTIVE` 失败关闭。SDK 内置 Tool 同样由固定策略和 Runtime 配置约束，不得因为没有 MCP Server 而误报远端缺失。

File Tool的输入Schema还必须通过真实bundled CLI注册回归。Claude CLI可能接受MCP `tools/list`，却静默排除含其不支持组合关键字的单个Tool；因此直接用`InMemoryTransport`调用Server只能证明bridge handler存在，不能证明CLI已暴露该Tool。对CLI Schema子集无法表达的跨字段不变量，保持File Service在副作用前的代码校验，并由真实CLI测试断言生产Tool清单和提交ToolUse均可达。

### 4. Prompt 的可调用工具声明从 Runtime effective registry 生成

Prompt 模板提供显式 `template_version`。所有肯定式的“当前可调用工具”和文件交付步骤由已验证的 Runtime effective registry 渲染；静态 Prompt 不再人工维护一份 `Available internal tools` 名单。渲染器同时生成：

- 传给模型的工具声明片段；
- 只含模板版本和有序 Tool 标识的 `prompt_contract_hash`；
- 供观测事件保存的有序声明列表。

Prompt declaration 中出现但 Runtime effective 中不存在的 Tool 为 `PROMPT_OVERCLAIM`，必须在首次模型请求前失败关闭。Runtime effective 中存在但 Prompt 未逐项介绍不自动失败；Tool 的函数 Schema 本身仍可作为调用说明。用于表达禁止、历史或错误示例的名称不得进入“当前可调用”结构化声明，也不得由自由文本扫描推断。

**备选方案：**对完整 Prompt 用正则提取 Tool 名。该方案无法可靠区分可调用声明、禁止语句和历史说明，还会诱导保存动态 Prompt，因此不采用。

### 5. 构建身份由构建和部署显式注入，不由容器自行猜测

Control Plane、Agent Worker、Python Runtime 和 File Service 都提供以下安全构建身份：

- `component`；
- `source_revision`；
- `build_id`；
- `platform`，使用标准 OS/architecture 形式；
- `image_digest`，仅在部署系统能够准确注入时提供。

构建阶段写入源码 revision 和 build ID；Compose/部署阶段可注入实际拉取的镜像 digest。服务启动时校验格式，缺失必需字段则 readiness 失败。禁止挂载 Docker socket、调用 Docker daemon 或把镜像 tag 伪装成 digest。

Control Plane 身份在 Job 创建时关联，Worker 身份进入 1.4 invocation 请求事实，Runtime 身份由 Runtime event 返回。File Service 在已认证 MCP `initialize` 响应的 namespaced experimental capability 中提供构建身份，File bridge 与同一 Session 的 `tools/list` 一并观测。所有身份都进入 request/observation hash 边界，不能由模型参数覆盖。

同一部署要求组件 `source_revision` 和 `build_id` 符合发布清单。Mac/Windows 或 amd64/arm64 的 `image_digest` 可以不同；平台不同本身不是漂移。若 revision/build ID 和工具契约 hash 一致，跨架构仍可判定契约一致；digest 仅用于定位实际产物。

### 6. 状态计算是确定规则，不使用模型结论

逐 invocation 总状态只有：

- `MATCH`：四层需要观测的事实已齐全，所有必需映射匹配，构建身份符合发布清单；
- `DRIFT`：任一失败关闭条件成立，或需要观测的事实无法取得；
- `NOT_OBSERVED`：该 invocation 属于历史 protocol 1.3、尚未开始 Runtime，或没有 1.4 观测事件。它不等于健康。

Job 列表汇总使用确定优先级：任一 invocation 为 `DRIFT` 则 Job 为 `DRIFT`；否则存在 1.4 观测且均为 `MATCH` 则为 `MATCH`；否则为 `NOT_OBSERVED`。重试不能用后一次 `MATCH` 掩盖先前 `DRIFT`。详情按 invocation 显示各层和逐工具矩阵，并明确区分 Job frozen、File MCP live 与 Runtime derived。

### 7. protocol 1.4 采用一次性切换并保留只读历史

协议目录、生成器、Worker client、Runtime、health/version、golden fixtures 和合同测试整体升级到 1.4。生产切换前停止入口，排空或显式取消所有非终态 1.3 Job、outbox 和 invocation，再一次性重建 Control Plane、Worker、Runtime、File Service 与管理端。不得运行双协议消费者，不提供 1.3 到 1.4 的请求投影。

protocol 1.3 的终态 Job 和安全 Runtime event 保留为只读审计事实；仓库级历史 Schema/安全投影器可以读取它们，但活动 Runtime 不可恢复、重放或调用模型。1.4 上线需要创建新的 Agent/Application Publication，不能修改已发布的 1.3 冻结事实。

## Risks / Trade-offs

- **File MCP 多一次 `tools/list` 往返：**增加 invocation 启动延迟。通过同一 MCP Session、一次完整分页和有界超时控制，不跨 Job 缓存，以免缓存掩盖部署漂移。
- **远端 Schema 规范化差异导致误报：**统一复用现有输入 Schema hash 算法，并用 golden fixtures 覆盖字段顺序、空可选字段和分页顺序；无法规范化时失败关闭。
- **观测事件随 Tool 数量增长：**沿用协议有界集合，保存名称和 hash 而非完整 Schema；超过协议上限时拒绝，不截断后宣称 `MATCH`。
- **构建 identity 可能由部署误填：**它是可审计发布证据而非远程证明。CI 生成 build manifest，readiness 与 Compose 验收交叉检查；`image_digest` 不可得时明确为空，不伪造。
- **严格失败关闭会使旧 Prompt 或旧 File Service 立即暴露问题：**这是预期行为。发布前通过合同测试和预检验证 1.4 全链路，避免在入口恢复后首次发现漂移。
- **历史 1.3 记录不能获得新观测：**界面显示 `NOT_OBSERVED`，不回填或根据当前 MCP 状态伪造历史结论。

## Migration Plan

1. 增加 protocol 1.4 Schema、错误码、limits、生成类型和 golden fixtures，并先让所有静态合同测试通过。
2. 增加前向 migration：保存 Job 工具契约汇总投影、Prompt 版本/hash 和扩展的 Runtime provenance；不重写既有 1.3 event、Snapshot 或 Publication。
3. 实现 File Service 构建身份声明、Runtime `tools/list` 预检、effective registry、Prompt 渲染、`tool_contract_observed` 事件及 Worker 幂等持久化。
4. 实现授权后的运行记录 API 与管理端列表/详情投影；历史记录显示 `NOT_OBSERVED`。
5. 创建新的 1.4 Agent/Application Publication，构建同一 source revision/build ID 的所有相关镜像，并分别记录各平台实际 digest。
6. 在维护窗口停止入口，确认没有非终态 1.3 Job、outbox、delivery 或队列积压；任一项非零则失败关闭。
7. 一次性执行 migration、替换所有消费者和生产者，验证 health 只声明 1.4，再运行无附件 Job、File MCP 读取和文件提交/交付的新鲜 E2E。
8. 入口恢复后不回滚到 1.3。若 1.4 已创建运行事实，使用 1.4 前向修复；只有在入口尚未恢复且未创建任何 1.4 Job 时，才可整体回退数据库和所有镜像。

## Open Questions

无。失败策略、证据粒度、构建身份口径、Runtime 1.4 升级和运行记录展示均已由用户确认。
