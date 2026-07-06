# agent-audit-permission Specification

## ADDED Requirements

### Requirement: Platform configuration authorization is policy checked
系统 SHALL 在平台配置 API 执行新增、修改、启停、导入和发布动作前检查操作者是否具有对应配置管理权限。

#### Scenario: Authorized admin updates topology
- **WHEN** 具备平台配置管理权限的操作者更新基地或车间配置
- **THEN** 系统允许更新并记录授权决策

#### Scenario: Unauthorized user updates topology
- **WHEN** 不具备平台配置管理权限的用户尝试修改资源绑定
- **THEN** 系统拒绝请求，记录拒绝原因，并且不写入配置变更

### Requirement: Platform configuration audit is linked to runtime audit model
系统 SHALL 将平台配置变更审计与现有 Agent 审计模型保持一致的 actor、entity、action、before、after 和 correlation 信息。

#### Scenario: Admin changes access grant
- **WHEN** 管理员修改某用户的车间访问授权
- **THEN** 系统记录配置审计，包含操作者、被修改实体、修改前摘要、修改后摘要和 correlation id

#### Scenario: YAML import updates resource binding
- **WHEN** YAML import 更新已有资源绑定
- **THEN** 系统记录该资源绑定的配置审计，并能关联到本次 import 操作

### Requirement: Runtime tool authorization can consume platform access grants
系统 SHALL 允许运行时工具授权从平台访问授权配置生成访问策略，且 MUST 保持只读工具风险边界。

#### Scenario: User has workshop grant
- **WHEN** Agent job 用户命中某车间的 read-only access grant
- **THEN** 运行时工具授权允许该用户访问该车间允许的只读资源

#### Scenario: User lacks grant
- **WHEN** Agent job 用户没有目标车间或资源的访问授权
- **THEN** 运行时工具授权拒绝工具调用并记录权限拒绝
