## MODIFIED Requirements

### Requirement: 模型连接测试必须使用真实受限Runtime并防止SSRF
系统 SHALL 提供模型连接测试动作，测试 MUST 使用保存后的模型连接和 active Secret，通过独立 Python Runtime 的官方 Claude Agent SDK 路径执行无工具、单轮、短超时探测。Python API MUST 先执行 RBAC、HTTPS、Provider host allowlist、userinfo、fragment、重定向、回环、链路本地和私网目标校验；Runtime MUST 再按固定 revision/config hash 解析连接。响应 MUST 只包含 Provider Host、模型、Runtime/SDK 版本、耗时和安全结果，不得包含 Key、Secret ref、Prompt、模型响应正文或内部异常详情。

#### Scenario: 测试已保存DeepSeek连接
- **WHEN** Secret 管理员测试已保存、host 被允许且 revision/config hash 固定的 DeepSeek Anthropic-compatible 连接
- **THEN** Python 服务把受限 probe 委托给 `python-agent-runtime`，Runtime 使用 active Key 完成无 Tool 探测并返回安全状态和耗时

#### Scenario: 测试未批准URL
- **WHEN** 管理员提交回环、私网、HTTP、带 userinfo 或 host 不在 allowlist 的 Base URL
- **THEN** Python 服务在调用 Runtime 前拒绝连接
- **AND** 审计只记录脱敏 host、actor、结果和 correlation ID

#### Scenario: 连接版本发生漂移
- **WHEN** Runtime 读取到的模型连接 revision 或 config hash 与 probe 请求不一致
- **THEN** Runtime 在调用 Provider 前失败关闭并返回稳定配置漂移错误

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 初始化固定 `python-v1` 的默认诊断 Agent；所有新 Agent Definition MUST 固定为 `python-v1`。历史 `typescript-v1` Agent Definition SHALL 保持原始 runtime kind 和引用可读，但 MUST NOT 再创建草稿、发布、回滚为当前版本或产生新 Job。

#### Scenario: 默认Python Agent初始化
- **WHEN** 系统完成 migration 和 seed
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 系统不再创建新的 `typescript-diagnostic-agent` 或其它 `typescript-v1` Agent

#### Scenario: 后端读取指定Agent
- **WHEN** API 或运行时按 Agent code 请求配置
- **THEN** repository 按通用多 Agent 模型返回对应定义及历史 runtime kind，而不是依赖单例配置表

#### Scenario: 创建TypeScript Agent
- **WHEN** 管理员或旧客户端请求创建 runtime kind 为 `typescript-v1` 的 Agent
- **THEN** 系统以稳定的不支持错误拒绝且不创建 Definition 或草稿

#### Scenario: 读取历史TypeScript Agent
- **WHEN** 管理员查看退役前已存在的 `typescript-v1` Agent
- **THEN** API 返回其只读定义、Publication 和 runtime 标签
- **AND** 不允许编辑、发布、回滚为当前版本或用于新执行

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Python Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、不可变 `python-v1` runtime kind、schema version 和 config hash 的不可变 publication snapshot。草稿不得覆盖 Definition 的 runtime kind；历史 TypeScript snapshot 只可读取，不得作为新草稿或 Publication 的种子。

#### Scenario: 编辑已发布Python Agent草稿
- **WHEN** 管理员修改已发布 Python Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新该 Agent 的新草稿 revision，现有 publication 与 runtime kind 保持不变

#### Scenario: 发布合法Python草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Python Agent 草稿
- **THEN** 系统创建包含 `python-v1` 的新不可变 publication，并更新该 Agent 的当前发布指针

#### Scenario: 草稿伪造Runtime
- **WHEN** 草稿 payload 的 runtime kind 不是 `python-v1` 或与 Agent Definition 不一致
- **THEN** 系统拒绝校验和发布且不创建 publication

#### Scenario: 历史TypeScript Publication生成草稿
- **WHEN** 管理员尝试从历史 `typescript-v1` Publication 创建、发布或回滚草稿
- **THEN** 系统拒绝变更并提示先创建或选择 Python Agent Publication

## ADDED Requirements

### Requirement: Agent管理界面只管理Python Runtime并只读展示历史TypeScript事实
Agent 管理 API 与前端 SHALL 只允许创建、编辑、校验、发布和回滚 `python-v1` Agent。页面 SHALL 对历史 `typescript-v1` Definition 和 Publication 显示明确的“已退役、只读”状态，不得把历史 runtime kind 映射或显示为 Python。

#### Scenario: 管理员创建并发布Python Agent
- **WHEN** 具备权限的管理员创建 Agent、保存合法草稿并发布
- **THEN** 页面和 API 固定使用 `python-v1`，且不提供 Runtime 选择控件

#### Scenario: 管理员查看历史TypeScript Agent
- **WHEN** 管理员打开退役前的 TypeScript Agent 或 Publication
- **THEN** 页面显示原始 `typescript-v1`、历史 revision/hash 和只读状态
- **AND** 编辑、发布、回滚为当前版本和新应用选择动作均不可用

#### Scenario: 旧客户端提交TypeScript Runtime
- **WHEN** 旧客户端在创建、草稿、发布或回滚请求中提交 `typescript-v1`
- **THEN** API 失败关闭并返回稳定迁移提示，不静默改写为 Python

## REMOVED Requirements

### Requirement: Agent管理界面必须支持两个Runtime Agent
**Reason**: TypeScript Agent Runtime 退役后，继续允许管理和发布 TypeScript Agent 会产生无法执行的新事实并维持双实现控制面。

**Migration**: 管理界面改为只创建和管理 Python Agent；历史 TypeScript Agent 与 Publication 保留原 runtime kind 并以只读退役状态展示。
