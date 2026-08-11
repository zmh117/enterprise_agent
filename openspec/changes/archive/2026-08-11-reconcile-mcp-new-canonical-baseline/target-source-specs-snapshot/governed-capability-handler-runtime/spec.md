# governed-capability-handler-runtime Specification

## Purpose
TBD - created by archiving change stabilize-platform-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: Capability Handler 实现必须来自代码注册表
系统 MUST 从代码加载稳定 Handler ID、不可变版本、输入/输出 schema、风险等级、所需权限和逻辑资源槽；数据库只能管理安装、治理与发布元数据。

#### Scenario: 发布已安装 Handler
- **WHEN** 数据库发布的 Handler ID 和版本存在于当前代码注册表
- **THEN** 系统可以将其标记为可参与运行时解析

#### Scenario: 数据库包含动态 Handler 内容
- **WHEN** 配置试图保存或执行 Python、脚本、SQL 模板或任意 URL 作为 Handler 实现
- **THEN** 系统必须拒绝

### Requirement: Handler 可执行集合必须满足全部治理交集
运行时 MUST 仅在 Handler 同时满足 installed、published、resource-bound、agent-allowed、application-allowed、role-allowed 和 scope-allowed 时执行。

#### Scenario: 任一授权维度缺失
- **WHEN** Handler 已安装且已发布，但当前角色未获授权
- **THEN** 系统必须拒绝调用并记录不含敏感数据的拒绝原因

### Requirement: Handler 逻辑资源槽必须在应用发布时绑定
Handler MUST 只声明逻辑资源槽，业务应用发布 MUST 将每个必需槽绑定到具体已发布 Resource Revision。

#### Scenario: 必需槽未绑定
- **WHEN** 业务应用尝试发布但某 Handler 必需资源槽没有有效 revision
- **THEN** 系统必须阻止应用发布

### Requirement: Job 必须固化不可变 Execution Scope
Job 创建时 MUST 固化业务应用发布、Handler 版本、Resource Revision 绑定及环境/基地/车间范围；Agent、Handler 和请求 payload 均不得在执行时扩展或替换该范围。

#### Scenario: Agent 请求另一个基地
- **WHEN** 工具参数指定的基地不在 Job 固化 Execution Scope
- **THEN** Internal API Platform 必须拒绝该调用且不访问目标资源

### Requirement: 通用数据库查询必须作为受治理的只读业务能力
`query_database` MUST 出现在业务应用 API 能力目录，但仍只允许调用代码内置的只读 Handler；平台不得因此新增面向外部调用方的公共查询端点。

#### Scenario: 业务应用选择通用数据库查询
- **WHEN** 业务应用在组成配置中选择 `query_database`
- **THEN** 平台必须允许保存和校验该能力，并继续要求 Agent、应用、角色、数据范围和数据库资源绑定全部通过

#### Scenario: 通用数据库查询缺少治理条件
- **WHEN** `query_database` 缺少已发布资源绑定、角色授权或 Execution Scope
- **THEN** 平台必须在访问数据库前拒绝调用
