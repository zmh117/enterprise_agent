## Context

当前系统已经具备以下可复用基础：

- `agent_definition`、`agent_revision`、`agent_publication` 提供 Agent 的稳定定义、草稿和不可变发布快照；
- `agent_workflow_template`、节点、边和 Workflow Publication 提供只读诊断流程配置；
- Channel、Webhook、Delivery 已经具备 connector、入口和出口配置，但入口仍直接选择全局或请求中的 Agent；
- `app_user`、`user_external_identity`、RBAC、Web Session、CSRF 和 Audit 已经形成统一身份与管理 API 安全基础；
- 前端已经完成控制面静态原型，但没有业务路由、API Client 或真实业务应用数据。

缺失的是一个位于这些能力之上的装配聚合：系统没有稳定的 Business Application ID，无法声明“哪个入口、哪个 Agent 发布版本、哪个 Workflow 发布版本、哪些能力策略和哪个投递出口共同构成一个可发布业务场景”。如果直接把现有资源继续绑定到全局默认 Agent，后续 ONES 身份、API Capability 和多渠道扩展都会把配置散落到各模块中。

本变更建立控制面事实模型和管理工作区，但不修改当前数据面。钉钉、Webhook、RabbitMQ、Agent Worker 和 Delivery 在本变更完成后仍沿用原路径，直到后续变更显式接入应用解析器。

## Goals / Non-Goals

**Goals:**

- 建立独立的 Business Application 聚合和 DDD 模块，不把应用逻辑塞进 Agent、Workflow 或 Admin 通用模块。
- 支持稳定应用定义、可编辑草稿、跨组件校验、不可变发布快照和环境级激活。
- 冻结 Agent、Workflow、Trigger、Channel、会话、投递和 Capability 引用，使一次发布可审计、可回溯、可重新激活。
- 提供确定性且只读的发布解析端口，为后续数据面按入口查找应用提供唯一契约。
- 提供经过身份、RBAC、CSRF、乐观并发和审计保护的管理 API。
- 将前端“业务应用”从静态卡片升级为真实列表、详情、组成配置、校验和发布历史工作区。
- 保持第一版只读 Agent 和独立 API 平台边界，不重新暴露数据库、Redis、Loki、任意 HTTP 或 Secret。

**Non-Goals:**

- 不把现有钉钉或 Webhook 入口切换到 Business Application Resolver。
- 不实现 Workflow 运行引擎或 AntV X6 流程画布；只引用现有 Workflow Publication。
- 不实现 API Capability 目录、OpenAPI 导入、Capability Gateway 或 ONES 需求/任务/缺陷查询。
- 不实现登录页面；前端复用现有 Web Session，未登录时只展示明确的未授权状态。
- 不创建新的 Agent Runtime，也不把每个业务应用部署成独立服务。
- 不允许草稿、发布或激活动作直接启动 Agent Job。
- 不保存任何外部系统密码、Token、Webhook Secret 或底层数据源连接信息。

## Decisions

### 1. Business Application 使用独立 bounded context

新增 `backend/app/modules/business_application/`，内部保持：

```text
domain/
  models.py
  policies.py
application/
  service.py
  ports.py
infrastructure/
  repository.py
api/
  controller.py
```

领域模块只通过端口读取 Agent Publication、Workflow Publication、Channel Connector 和未来 Capability Catalog，不直接依赖这些模块的 Repository 实现。Bootstrap 负责组装适配器。

选择独立模块而不是扩展 `agent_config`，因为 Agent Profile 是可复用执行配置，Business Application 是面向入口和业务场景的装配与发布单元，二者具有不同生命周期。也不把命令写进 `admin` 模块；`admin` 继续承担跨域只读查询和平台总览。

### 2. 稳定定义、草稿修订、发布快照和环境激活分层存储

新增以下表：

```text
business_application
business_application_revision
business_application_revision_trigger
business_application_revision_delivery
business_application_revision_capability
business_application_publication
business_application_deployment
```

`business_application` 保存稳定身份：

```text
id
code
name
description
project_code
owner_user_id
status
revision
created_by / created_at / updated_at
```

`business_application_revision` 保存一次完整草稿：

```text
id
application_id
revision
status
agent_publication_id
workflow_publication_id
session_policy_json
execution_policy_json
validation_json
config_hash
created_by / created_at / updated_at
```

一对多的 Trigger、Delivery 和 Capability 引用使用修订子表，不存进不可查询的大 JSON；会话和执行策略属于小型、强内聚值对象，使用受 schema 约束的 JSON。

`business_application_publication` 保存不可变规范化快照、schema version、hash、来源 revision 和发布人。`business_application_deployment` 以 `(application_id, environment)` 唯一，指向当前激活的 publication。发布和激活分离，发布不会自动影响任何环境。

采用这一分层而不是在 `business_application` 上直接维护一份可变 JSON，是为了保证草稿编辑不污染已发布运行配置，并使回滚只需重新指向历史 publication。

### 3. 应用引用组件发布版本，不复制或追随组件草稿

应用草稿必须引用：

- 一个有效的 `agent_publication_id`；
- 零个或一个 `workflow_publication_id`；
- 零个或多个 Trigger Binding；
- 零个或多个 Delivery Binding；
- 零个或多个 API Capability 编码与可选版本约束。

发布快照记录组件 ID、稳定编码、revision/version 和 config hash，但不复制 Agent 或 Workflow 的内部完整配置。Agent Publication 与 Workflow Publication 已经不可变，使用引用加 hash 足以保证一致性，也避免同一配置在多个应用中重复。

如果被引用组件不存在、已禁用、hash 校验失败或项目范围不兼容，应用发布必须失败。应用发布以后，组件的新草稿或新发布不会改变旧应用快照；需要升级时必须创建新的应用 revision。

### 4. Capability 使用显式验证端口，不与现有内部工具混为一谈

定义 `CapabilityCatalogReader` 端口：

```text
resolve(code, version_constraint, environment) -> CapabilityReference
```

本变更不实现真实 Capability Catalog。初始适配器只允许空 Capability 列表；任何非空编码都返回“目录尚未接入”的可操作校验错误。数据表和快照 schema 现在就保留 Capability 引用，是为了下一阶段接入时不再破坏应用发布模型。

不使用现有 `ToolRegistry` 代替 API Capability，因为内部数据库/Redis/Loki 工具和独立 API 平台发布的业务能力具有不同的安全责任、版本和审计语义。

### 5. Trigger Binding 使用规范化路由键并在激活时检查冲突

Trigger Binding 至少包含：

```text
trigger_type
connector_id
routing_key
actor_policy
service_account_user_id
enabled
config_json
```

`actor_policy` 第一版仅允许：

- `CURRENT_SENDER`：钉钉私聊或群聊按当前消息发送人解析内部身份；
- `SERVICE_ACCOUNT`：Webhook 等非人员入口使用已存在且启用的内部服务主体。

Secret、完整 Webhook URL、Token 和任意请求 Header 不得进入 `config_json`。这里只保存 connector ID、Webhook Definition ID、会话策略等非敏感引用。

激活时以：

```text
environment + trigger_type + connector_id + routing_key
```

检查所有已激活应用，拒绝冲突。这样后续运行时解析不依赖优先级猜测。发布阶段只检查单个快照内部重复，环境间冲突在激活时检查。

### 6. 发布校验、快照生成和激活必须事务化

发布流程：

```text
加载 application 和指定 revision
  → 校验乐观并发与应用状态
  → 解析 Agent/Workflow/Channel/Capability 引用
  → 校验 actor、session、execution 和 delivery 策略
  → 生成 canonical snapshot
  → 计算 SHA-256
  → 同一事务写 publication、validation 和 audit outbox/审计记录
```

激活流程：

```text
验证 publication hash 和 schema
  → 校验 application/environment 状态
  → 检查路由键冲突
  → 乐观更新 deployment
  → 记录 activation audit
```

同一个 revision 的重复发布使用 `(application_id, revision)` 唯一约束保证幂等；同一 publication 重复激活返回当前 deployment，不重复制造版本。

### 7. Resolver 是只读控制面端口，本变更不接入数据面

提供两个应用层读方法：

```text
resolve_active(application_code, environment)
resolve_trigger(environment, trigger_type, connector_id, routing_key)
```

返回内容包括应用稳定标识、publication ID、Agent/Workflow发布引用、Trigger、Delivery、Capability引用、策略和完整性状态，不返回 Secret。

Resolver 对无匹配、重复匹配、停用应用、未激活环境、hash 不一致和不支持 schema 返回明确的非重试配置错误。第一版只为测试和后续适配提供端口，不在钉钉、Webhook 或 Job 创建服务中调用；这避免一次变更同时引入控制面和生产路由切换。

### 8. 管理 API 遵循现有身份、权限、CSRF和错误契约

API 前缀：

```text
GET    /api/admin/business-applications
POST   /api/admin/business-applications
GET    /api/admin/business-applications/{code}
PUT    /api/admin/business-applications/{code}
PUT    /api/admin/business-applications/{code}/draft
POST   /api/admin/business-applications/{code}/validate
POST   /api/admin/business-applications/{code}/publish
GET    /api/admin/business-applications/{code}/publications
POST   /api/admin/business-applications/{code}/environments/{environment}/activate
POST   /api/admin/business-applications/{code}/environments/{environment}/deactivate
GET    /api/admin/business-applications/{code}/effective
```

权限资源使用 `business_application`，动作分为 `read`、`create`、`edit`、`publish` 和 `activate`。列表查询只返回当前主体有权读取的项目/应用；无权访问具体对象时返回 404，避免枚举。所有状态变更要求现有 Web Session 和 CSRF。

请求模型使用 `extra="forbid"`、长度限制和枚举；所有写请求携带 `expected_revision`。冲突返回 409，字段校验返回 422，权限失败沿用现有安全错误映射。

### 9. 前端只把“业务应用”升级为真实工作区

引入 React Router 和 TanStack Query，结构如下：

```text
frontend/src/
  app/router/
  shared/api/
  contexts/applications/
    domain/
    application/
    infrastructure/
    presentation/
```

- `domain`：页面需要的应用、revision、publication 和 deployment 类型；
- `application`：查询 key、用例 hooks 和表单 schema；
- `infrastructure`：仅包含 Business Application API Client；
- `presentation`：列表、详情、组成配置、校验结果和发布历史页面。

首页保留现有产品地图，但“业务应用”菜单进入真实列表。应用详情第一版包含：

- 概览；
- 组成配置；
- 校验结果；
- 发布历史和环境激活状态。

流程设计只展示被引用 Workflow Publication 和“后续提供画布”的状态。Capability 列表在目录未接入时只能为空并明确说明，不允许用户录入任意 HTTP、SQL 或工具名。

前端不实现登录页；所有请求使用 `credentials: include`，写请求从现有 CSRF Cookie 读取值并发送 `X-CSRF-Token`。401 显示“需要登录到管理会话”，403 显示“无业务应用权限”，不会回退到虚假静态成功数据。

### 10. 功能开关保护真实控制面，不改变现有默认链路

新增 `FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE`，默认关闭时不注册写 API，前端保持原型说明；开启后开放真实应用工作区。Resolver 单元可以始终装配供测试使用，但没有任何现有入口调用它。

不新增“自动路由到业务应用”的隐式开关。后续数据面接入必须使用单独 OpenSpec 变更，明确迁移入口 binding、灰度、回退和端到端验证。

### 11. 所有敏感和变更行为均可审计

审计事件至少包括：

```text
business_application.created
business_application.updated
business_application.draft_saved
business_application.validated
business_application.published
business_application.activated
business_application.deactivated
business_application.status_changed
```

审计 payload 只记录 application code、revision/publication ID、environment、组件 ID、config hash、actor 和结果，不记录策略原文中的敏感数据、凭据、Webhook URL 或上游响应。

## Risks / Trade-offs

- [控制面已发布但数据面仍不使用，用户误认为立即生效] → 发布和激活页面明确显示“尚未接入入口运行时”，API 响应返回 `runtime_wired=false`，文档说明当前默认链路不变。
- [应用、Agent和Workflow分别发布导致版本组合复杂] → 应用快照冻结每个组件的 publication ID、revision 和 hash，升级任何组件都必须创建新应用 revision。
- [先预留 Capability 字段会被误用为任意工具入口] → 初始 Catalog Adapter 拒绝所有非空 Capability，前端不提供自由文本编辑；下一阶段只能通过目录选择。
- [Trigger 路由键设计不足以覆盖未来渠道] → 使用 `trigger_type + connector_id + routing_key` 的最小稳定契约，并把渠道特有非敏感字段放入受 schema 约束的 config；新增 trigger type 时扩展校验器。
- [通用 JSON 策略失去字段治理] → 每类策略使用严格 Pydantic/领域值对象校验、canonical JSON 和 schema version，不接受未知字段。
- [新增真实页面需要登录但当前未做登录 UI] → 复用现有会话，提供明确 401 状态；登录 UI 保持独立变更，测试使用现有认证夹具。
- [激活冲突在并发请求下漏检] → 冲突查询和 deployment 更新放入事务，并增加可由数据库强制执行的规范化激活路由投影或锁。
- [迁移影响现有默认 Agent] → 不自动激活、不修改 ingress/job 表和现有配置；新表为空也不影响运行时。

## Migration Plan

1. 新增数据库迁移，创建 Business Application 相关表、外键、唯一约束和索引，不修改现有 Agent、Workflow、Channel 或 Job 数据。
2. 实现领域模型、Repository、组件读取端口、校验、发布、激活和 Resolver，并先以单元/Repository集成测试验证。
3. 注册受功能开关保护的管理 API、权限能力和审计事件；默认关闭写入口。
4. 提供幂等本地 seed/CLI，可创建未激活的 `default-diagnostic-application` 草稿并引用当前默认 Agent/Workflow Publication；生产环境不自动执行。
5. 实现前端真实业务应用路由和工作区，保留其余静态原型区域。
6. 在测试环境开启功能开关，验证创建、并发冲突、校验失败、发布、激活、重新激活旧版本和停用。
7. 验证现有钉钉、Webhook、Agent Job 和 Delivery 行为完全未变化后再合并。

回滚时先关闭功能开关并停用前端入口；新表为纯新增，可保留数据。若必须数据库回滚，只有在确认没有后续变更引用这些表时才删除新表。现有数据面无需回滚。

## Open Questions

无。本阶段确定只建立控制面装配、发布和读取基础；Capability Catalog、入口运行时接线、完整流程画布和登录页面均使用后续独立变更处理。
