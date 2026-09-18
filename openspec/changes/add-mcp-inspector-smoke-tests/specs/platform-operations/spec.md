## ADDED Requirements

### Requirement: Inspector 必须作为固定版本开发测试客户端运行
仓库 SHALL 提供官方 MCP Inspector CLI 的精确版本开发依赖和可重复安装的锁文件，并声明兼容 Node 版本。Inspector MUST 只用于开发与 CI，不进入生产服务依赖。测试调用 MUST 使用已经安装且版本匹配的本地 CLI，不在测试执行期间解析 latest、联网安装或等待交互输入。

本地 Node MUST 满足开发包 `engines.node` 声明的正式版最低要求 `>=22.19.0`；CI SHALL 继续使用 `.node-version` 指定的精确版本，该 pin MUST NOT 被用作本地相等约束。

#### Scenario: 使用锁定依赖运行
- **WHEN** 开发者或 CI 完成显式依赖安装并启动 Inspector 测试
- **THEN** 测试核验本地 Inspector 版本并使用同一固定 CLI 执行 MCP 请求
- **AND** 报告实际 Inspector、Node 与 Python 版本

#### Scenario: 本地使用满足最低要求的更高 Node 版本
- **WHEN** 已安装的 Node 正式版等于或高于 22.19.0，包括更高 patch、minor 或 major
- **THEN** Node 版本检查通过，不要求等于 CI 的精确版本

#### Scenario: 必需依赖缺失或漂移
- **WHEN** 已显式启用 Inspector 测试但 Node、CLI 不可用，Node 不满足最低正式版要求，或 Inspector 安装版本不匹配
- **THEN** 测试以稳定中文诊断失败，不自动安装、不跳过、不报告通过

### Requirement: Inspector 冒烟测试必须经过隔离的项目真实 HTTP 应用
一期 Inspector 测试 SHALL 使用项目 `tool-mcp` 的现有应用工厂和标准 Streamable HTTP，在回环地址实际监听，并由独立 Inspector 子进程访问。测试 MUST 使用隔离测试数据库、合成资源、有效 Publication/角色授权、经创建和 claim 的 RUNNING Job 及其冻结工具快照；外部资源访问 SHALL 使用有调用记录的测试替身。测试 MUST 保留真实授权、资源解析和审计代码，不启用 direct-job 权限放宽替身，不修改生产 Server 的 Host、防护、Schema 或鉴权规则以适配 Inspector。

#### Scenario: 通过实际 HTTP 调用代表工具
- **WHEN** Inspector 调用测试 Job 已授权的 `get_schema_directory`
- **THEN** 请求经过实际 HTTP、项目 MCP 应用、真实治理链和合成 Schema 资源读取
- **AND** 测试检查已知表列结果与资源替身调用事实，不能以 TestClient 回包或仅检查健康接口代替

#### Scenario: 测试上下文与宿主环境隔离
- **WHEN** 测试准备服务或启动 Inspector
- **THEN** 只使用本次创建的测试数据、临时配置和独立 Inspector 状态目录，不加载真实环境配置、用户 OAuth 状态或生产凭据
- **AND** 正常 `tool-mcp` 请求使用受信执行 Header，非法 Authorization 测试只使用固定假值

#### Scenario: 测试失败或取消
- **WHEN** 服务启动失败、调用超时、断言失败或测试取消
- **THEN** 测试在有界时间内回收 Inspector 子进程、停止 HTTP 服务、关闭测试数据库并清理临时文件
- **AND** 不通过自动重试隐藏失败，不访问或清理用户现有业务数据

### Requirement: Inspector 必须核对授权工具声明和精确调用证据
Inspector 套件 SHALL 覆盖连接、授权工具列表、代表性成功调用及连续同名调用。`tools/list` 的名称集合 MUST 与当前测试 Job 授权且属于 `tool-mcp` 的精确集合一致；返回 `inputSchema` MUST 使用既有 hash 口径与代码 Manifest 和冻结快照核对。成功调用 MUST 断言业务内容、MCP 成功标记、资源访问事实，以及结果关联标识与本 Job 工具审计记录的一致性，不以 HTTP 200、CLI 退出码为零或列表非空单独判定成功。

#### Scenario: 工具列表符合冻结合同
- **WHEN** Inspector 获取测试 Job 的工具列表
- **THEN** 工具名称集合和输入 Schema 与该 Job 允许集合精确匹配
- **AND** 全局已注册但未发布给该 Job 的工具不得被当作应有工具补入期望或快照

#### Scenario: 返回与审计一致
- **WHEN** 代表性工具调用成功
- **THEN** 返回合成资源的预期数据，且 `_meta` 中 `enterprise-agent/mcp-call-id` 和 `enterprise-agent/agent-tool-call-id` 与本 Job 持久化审计精确关联

#### Scenario: 连续同名调用不串联
- **WHEN** 同一测试 Job 连续成功调用相同工具两次
- **THEN** 两次调用具有不同关联标识，各自只关联自己的 Tool Call 与 MCP 审计记录

### Requirement: Inspector 负向测试必须区分客户端拒绝和服务端拒绝
Inspector 套件 SHALL 包含非法参数、快照外工具、缺少执行上下文和非法 Authorization 的负向场景。测试 MUST 同时判断预期失败类别、可取得的稳定项目错误码与资源替身零调用事实。Inspector 在客户端提前拒绝时 MUST 如实标注客户端拒绝，不将其声称为服务端验证；至少一个场景 MUST 证明请求进入服务端调用校验后被拒绝。连接失败、未知 CLI 错误或任意非零退出码不得替代预期的业务拒绝。原有低层 HTTP 负向测试 MUST 继续保留。

#### Scenario: 缺少调用所需执行 Header
- **WHEN** 保留有效 Job Header 及可列举工具的条件，但调用缺少必要执行身份 Header
- **THEN** 测试核对服务端 `tool_mcp_context_missing`，并证明资源替身未被调用

#### Scenario: 客户端先拒绝非法输入或工具
- **WHEN** 固定版本 Inspector 在发送工具请求前拒绝非法参数或不可见工具
- **THEN** 测试结果明确标注客户端拒绝与对应类别，不记录服务端拒绝已验收
- **AND** 不能为了让请求发出而改写生产工具 Schema 或扩大测试 Job 授权

#### Scenario: 未授权工具和非法 Authorization
- **WHEN** 测试请求快照外工具，或使用固定假 Authorization Header 访问 `tool-mcp`
- **THEN** 调用不能成功，资源替身调用次数保持为零，并核对对应拒绝类别

#### Scenario: 连接故障不是权限拒绝
- **WHEN** 负向场景实际得到连接超时、服务不可达或未知客户端失败
- **THEN** 该场景失败，不能因 CLI 返回非零退出码就认定权限边界通过

### Requirement: Inspector 必须接入显式测试入口和失败关闭的 CI 门禁
新 Inspector 测试文件 MUST 唯一登记到既有 `integration` 层。仓库 SHALL 提供显式本地命令及独立 CI job，使用相同场景和固定依赖；CI job MUST 在工作流覆盖的 PR/push 事件执行，并作为现有镜像构建的前置成功条件。默认快速套件 MUST 保持现有选择范围；普通完整套件未显式启用 Inspector 时 SHALL 显示明确跳过原因。显式本地入口与专用 CI 中，缺依赖、零用例、全部跳过、必需场景缺失或任一失败 MUST 导致非零结果。

#### Scenario: 普通快速与完整回归
- **WHEN** 开发者执行现有快速或未启用 Inspector 的完整测试入口
- **THEN** 快速套件保持 unit/contract 选择，完整套件保留全部旧测试并明确报告 Inspector 集成测试未启用

#### Scenario: 显式 Inspector 验证
- **WHEN** 开发者运行专用命令或 CI 执行 Inspector job
- **THEN** 必需场景实际执行，任何缺失或失败都使入口失败，不能使用 continue-on-error 或静默 skip 获得成功

#### Scenario: Inspector 门禁失败
- **WHEN** 专用 CI job 失败
- **THEN** 依赖该门禁的镜像构建不得执行，旧测试通过不能覆盖此失败

### Requirement: Inspector 引入必须保留旧覆盖并明确验收证据边界
本次接入 MUST 保留现有业务、HTTP 合同、SDK/Runtime、事务、恢复及写操作确认测试；共享夹具抽取不得减少原场景或断言。验收 SHALL 记录旧测试与新增测试的执行环境、版本、收集数、结果、跳过原因和耗时，列出新增独立客户端覆盖与仍未覆盖的范围。所有结果 MUST 区分项目真实 HTTP 加合成资源、真实 Provider、实际部署和完整 Agent 业务链路；没有对应运行证据时不得宣称后几类已通过或给出准确率提升百分比。测试报告不得包含真实认证材料或原始业务消息。

#### Scenario: 夹具抽取后回归
- **WHEN** 旧测试改为复用 support 中的夹具
- **THEN** 相同测试选择下原用例、断言和拒绝/恢复覆盖保持，证据列出实际运行差异

#### Scenario: 本地 Inspector 套件通过
- **WHEN** 全部一期场景使用项目服务与合成 Schema 资源通过
- **THEN** 只报告 `tool-mcp` 的独立客户端和回环 HTTP 验证通过，不声称真实数据库、ONES、钉钉、File MCP、发布镜像或模型工具选择已验收

#### Scenario: 验收尚未完成
- **WHEN** Linux CI、真实部署或外部 Provider 缺少运行证据
- **THEN** 分别保留未验证状态，不能因提案校验或本地测试通过而补记完成
