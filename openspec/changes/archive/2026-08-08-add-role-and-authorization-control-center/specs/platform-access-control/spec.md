## MODIFIED Requirements

### Requirement: Platform enforces environment/base/workshop access scope
系统 SHALL 在当前业务应用上下文内强制执行平台侧环境、基地和车间访问范围，该范围独立于并叠加在 Agent 工具安全上限之上。平台 MUST 使用角色为该业务应用保存的明确资源集合，不得把一个应用的范围用于另一个应用，也不得让“当前全部”自动包含未来新增资源。

#### Scenario: In-scope request allowed
- **WHEN** 用户在当前业务应用下被明确授权访问 `sanjiu`/`guanlan`/`GL001` 并请求该目标
- **THEN** 平台允许请求继续解析和执行

#### Scenario: Out-of-scope base rejected
- **WHEN** 用户在当前业务应用下只被授权访问 `sanjiu`，但请求 `mmk`
- **THEN** 平台以不可重试授权错误拒绝请求

#### Scenario: Out-of-scope workshop rejected
- **WHEN** 用户在当前业务应用下只被授权访问车间 `GL001`，但请求 `GL002`
- **THEN** 平台拒绝请求并记录目标业务应用和范围摘要

#### Scenario: Scope does not cross applications
- **WHEN** 用户在应用 A 被授权某基地，但在应用 B 没有该基地授权
- **THEN** 从应用 B 发起的工具请求不得复用应用 A 的范围

## ADDED Requirements

### Requirement: 当前全部展开为明确范围
系统 SHALL 在保存授权时把“当前全部环境、基地或车间”展开为当时存在且操作者有权授予的明确资源 ID 集合，并 MUST NOT 提供包含未来新增资源的动态全部选项。

#### Scenario: 新基地在授权后创建
- **WHEN** 管理员保存当前全部基地后新增一个基地
- **THEN** 新基地不进入既有角色授权，除非管理员再次编辑并明确选择

