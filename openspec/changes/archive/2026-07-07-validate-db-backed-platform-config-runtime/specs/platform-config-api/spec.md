## ADDED Requirements

### Requirement: Imported topology can be verified as runtime-ready
系统 SHALL 让通过 YAML import 或平台配置 API 写入的 topology 能被验证为 Internal API Platform 可消费的 runtime snapshot。

#### Scenario: YAML import produces database snapshot
- **WHEN** 管理端导入合法 topology YAML 到 PostgreSQL
- **THEN** `/api/platform/topology-snapshot` 返回 source 为 database 或可被运行时加载的 DB-backed snapshot，并包含启用资源数量和访问授权摘要

#### Scenario: Imported topology has validation errors
- **WHEN** 导入后的启用资源绑定缺少运行时必须字段
- **THEN** snapshot API 返回配置错误详情，并且不得把该配置标记为 runtime valid

### Requirement: Platform configuration API supports runtime verification workflow
系统 SHALL 提供足够的只读 API 输出，让开发者或后续 Web 平台确认当前 DB 配置能驱动只读诊断工具。

#### Scenario: Verify effective topology
- **WHEN** 开发者查询平台 topology snapshot
- **THEN** 响应包含启用 environment/base/workshop、resource binding 作用域、resource kind、secret reference 摘要和配置 revision/hash

#### Scenario: Verify disabled resource exclusion
- **WHEN** 管理端禁用某个 resource binding 后查询 topology snapshot
- **THEN** snapshot 不包含该禁用资源，且 revision/hash 发生可观测变化

### Requirement: Platform configuration API documents restart or reload semantics
系统 SHALL 明确说明 DB-backed 配置对 Internal API Platform 的生效时机。

#### Scenario: Runtime uses startup snapshot
- **WHEN** Internal API Platform 采用启动时 snapshot 模型
- **THEN** 文档和验证流程明确要求修改配置后重启服务或执行未来的 reload 动作才能让运行时读取新配置
