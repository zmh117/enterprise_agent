## Context

当前系统已经存在 `rbac_role`、`rbac_user_role`、`permission_policy`、`platform_access_grant` 和统一 `AuthorizationEvaluator`，管理 API 也已覆盖角色、成员和原始权限策略。但前端只有人员与外部身份页面，导航是静态配置，用户详情没有角色管理；现有 OpenSpec 任务中“角色授权页面已完成”的状态与当前代码不一致。

运行时授权目前分散在多个层次：

```text
外部身份已绑定
  ∩ connector 允许 ingress
  ∩ project:<code>:use
  ∩ agent:<code>:use
  ∩ tool:<code>:use
  ∩ platform_access_grant
  ∩ Agent publication 工具分配
  ∩ 只读风险策略
```

这套交集在安全上是必要的，但把底层实现对象直接暴露给管理员，导致“身份已经绑定但用户仍无权使用 Agent”的结果难以配置和解释。业务应用已经成为渠道路由、Agent publication、执行策略和投递绑定的组合边界，因此用户运行授权也应以业务应用为入口对象。

本 change 横跨身份授权、业务应用、Agent job、Worker、工具平台、投递和前端管理台。当前只保留 `local` 运行环境，当前 Agent 继续保持只读诊断边界。现有工作区和数据库中有旧角色、成员和策略，本 change 只能使用加法 migration，不得清理或覆盖；清理和新建管理员由后续独立 change 负责。

## Goals / Non-Goals

**Goals:**

- 让一个统一自定义角色同时承载管理后台能力和业务应用访问能力。
- 用后端注册的稳定能力目录统一驱动前端显示与后端强制授权。
- 将业务授权表达为应用、只读能力和应用内明确数据范围，隐藏底层项目和 Agent 手工组合。
- 支持成员有效期、角色级分配委派、分区编辑、资源级管理范围和不可自我提权。
- 让授权保存后立即影响 job 创建、Worker 启动、工具调用和结果投递。
- 提供中文、可解释、secret-safe 的有效权限预览和审计。
- 保留旧策略兼容读取，为后续清空授权数据和严格切换提供安全过渡。

**Non-Goals:**

- 不在本 change 中删除任何现有人员、身份、角色、成员、策略或平台 grant。
- 不创建新的共享管理员账号，不生成或输出初始密码。
- 不引入授权草稿发布、审批流、角色版本历史或一键回退。
- 不提供包含未来资源的动态通配授权。
- 不允许角色授予写数据库、修改 Redis、Shell、文件写入或其它非只读工具。
- 不新增组织架构、用户组、部门同步、SSO 或自助申请权限。
- 不把业务应用负责人隐式视为授权管理员。

## Decisions

### 1. 使用统一角色，系统保护属性与用途标签分开

保留 `rbac_role` 作为唯一角色聚合根，不另建“管理角色”和“业务角色”两套表。为角色增加：

```text
origin: system | custom
protected: boolean
purpose_tags: string[]
metadata_revision
admin_revision
business_revision
membership_revision
```

`platform-admin` 是 `origin=system, protected=true` 的受保护角色。平台管理、业务访问只作为模板和标签，因为用户已确认自定义角色需要同时包含两类能力。

替代方案是用互斥 `role_type=admin|business`。该方案边界简单，但会迫使一个真实岗位维护多个角色，并与“自定义角色更强”的目标冲突，因此不采用。

角色 code 仅在创建前可调整，创建后不可变。自定义角色不物理删除，只通过 `enabled/disabled` 状态控制；停用不删除配置、成员和审计。

### 2. 管理能力目录由代码注册，授权事实按稳定能力编码持久化

扩展现有 `ADMIN_CAPABILITIES` 为唯一的 `AdminCapabilityCatalog`。每个定义至少包含：

```text
code
display_name_zh
module
action
risk_level
dependencies[]
resource_scope_kind
assignable
```

目录通过只读 API 提供给前端。前端不能提交未注册 code；后端将 code 解析为实际资源和 action 后再次授权。路由、按钮或 React 组件 ID 不进入授权事实。

新增规范化的角色管理能力绑定表：

```text
rbac_role_admin_capability
  role_id
  capability_code
  resource_type
  resource_code
  status
```

资源可限定到具体业务应用、Agent、渠道或目标角色。没有资源维度的能力使用目录声明的固定资源。唯一约束覆盖角色、能力和资源选择器，防止重复事实。

替代方案是继续让前端直接写 `permission_policy(resource_type, action)`。这会把内部协议暴露给普通管理员、无法验证能力依赖，也无法稳定生成中文 UI，因此仅保留 `permission_policy` 作为旧策略和高级例外事实。

### 3. `platform-admin` 只旁路管理能力，不旁路业务数据权限

管理授权 evaluator 在识别到启用的 `platform-admin` 人员成员关系时，对目录中 `module=admin` 的当前及未来能力直接允许。业务应用 invoke、业务能力和平台数据范围继续走普通角色授权，不因 `platform-admin` 自动允许。

最后一名平台管理员保护必须在同一个数据库事务中锁定相关用户、角色和成员行后再判断，覆盖：

- 停用最后一名管理员用户；
- 停用或到期其成员关系；
- 停用系统角色；
- 移除最后一名成员。

非最后一名管理员可以二次确认后移除自己的管理角色；成功后撤销或刷新当前 principal capability summary，防止旧页面继续显示操作入口。API 仍独立鉴权。

### 4. 业务访问使用规范化的应用授权聚合

新增：

```text
rbac_role_application_access
  id
  role_id
  application_id
  status

rbac_role_application_capability
  application_access_id
  capability_code

rbac_role_application_scope
  application_access_id
  environment_id
  base_id nullable
  workshop_id nullable
```

每个 scope 行保存明确资源 ID，不允许代表未来资源的通配符。“当前全部”由 application service 在提交事务中展开为操作者当前有权授予且当时存在的明确节点。

能力 code 来自业务应用能力目录，并在提交时验证：

```text
应用已装配
∩ Agent publication 已分配
∩ 平台工具已启用
∩ runtime registry 已注册
∩ risk=read-only
```

如果之后应用或 Agent 收紧能力，角色事实可以保留用于提示，但有效集合立即排除该能力。管理员页面显示“已被应用或 Agent 安全上限阻止”，不自动删除授权事实。

替代方案是在现有 `platform_access_grant` 增加 application code 和 JSON 工具集合。JSON 难以做外键、差异预览、逐项委派和一致性约束，因此新配置使用规范化表；旧 grant 继续由兼容 evaluator 读取，直到独立重置 change 清理。

### 5. 业务应用 invoke 封装底层项目和 Agent 入口许可

新授权链：

```text
身份/服务账号启用
  ∩ connector ingress
  ∩ Business Application active + deterministic route
  ∩ role application invoke
  ∩ application capability
  ∩ application-scoped explicit topology
  ∩ Agent/平台只读安全上限
```

应用 invoke 只封装该应用已经固定的 project 和 Agent 运行入口，不替代应用激活、publication 完整性、Execution Policy、connector 或工具安全校验。Debug API 或不经过业务应用的直接 Agent 调用仍可使用独立 `agent:use` 管理边界。

为避免首次部署立即中断旧用户，增加内部授权模式：

```text
compatibility
strict_application_role
```

`compatibility` 决策顺序：

1. 命中应用级显式 deny：拒绝。
2. 命中新角色应用 allow：按新模型继续。
3. 没有应用级决策：允许现有 project + agent 策略按原行为求值，并在 trace 标记 `legacy_compatible=true`。

本 change 默认部署在兼容模式，但必须在测试中覆盖严格模式。后续 `reset-identity-and-authorization-bootstrap` 在清理并建立新管理员后切换严格模式。兼容模式不得让旧 allow 绕过任何新显式 deny。

### 6. 授权区独立 revision，区内批量原子保存

角色详情不同区域由不同管理员维护，因此不能使用一个全局 revision 覆盖所有子项。采用：

```text
metadata_revision
admin_revision
business_revision
membership_revision
```

API 按授权区提供 typed DTO：

```text
PUT /api/admin/roles/{id}/metadata
PUT /api/admin/roles/{id}/admin-capabilities
PUT /api/admin/roles/{id}/business-access
POST /api/admin/roles/{id}/members:batch
```

每次提交校验 `expected_revision`，在一个数据库事务中锁定角色、校验操作者可授权范围、验证完整候选集合、替换该区事实、递增 revision 和写审计。任一步失败全部回滚。请求不得携带或覆盖无权编辑的其它授权区。

成员关系增加 `expires_at`、`assigned_by` 和可选的安全来源字段。角色详情批量维护和人员详情多角色维护调用同一个 membership application service。延长有效期复用普通成员更新审计，不引入独立审批事件。

### 7. 角色分配权和授权编辑权分开

管理能力目录注册角色级 `roles.assign` 能力，resource code 为目标角色 code。能编辑管理能力或业务访问不自动获得成员分配权。

业务授权管理员的可授权范围由管理能力绑定表达，例如：

```text
applications.authorization.manage:<application_code>
platform_scope.authorization.manage:<scope_node_id>
roles.assign:<role_code>
```

授权 service 计算“操作者可授予集合”，而不是复用操作者本人运行 Agent 的“可使用集合”。复制角色、批量成员、修改角色都必须使用候选集合做子集校验。人员管理员只有 `users.manage` 时不能分配平台角色。

### 8. 直接用户策略只作为高级例外

普通管理 UI 不提供给单个用户逐条配置应用、工具或数据范围的入口。人员详情仅允许分配角色并查看有效权限。

现有 `permission_policy(subject_type=user)` 和直接 `platform_access_grant` 在“高级授权例外”中显示，只允许平台权限管理员编辑。新业务访问默认只创建 allow；显式 deny 只在高级例外中创建，并继续执行 deny 优先。

### 9. 钉钉身份绑定和初始角色必须原子

扩展身份绑定 application command：

```text
BindExternalIdentityCommand
  target_user_id
  candidate / external identity
  initial_role_ids[]
  bind_without_access_confirmed
  expected revisions
```

事务顺序：

1. 锁定候选、目标用户和目标角色；
2. 校验身份唯一性、用户/角色状态和操作者分配权；
3. 创建或启用身份；
4. 创建全部成员关系；
5. 将发现候选切换为已绑定；
6. 写一组关联审计；
7. 提交。

任一初始角色失败则整个绑定回滚，候选继续显示。选择零个角色必须由前端显式提交 `bind_without_access_confirmed=true`，防止遗漏选择被误当成授权成功。

### 10. 有效权限解释使用专用只读服务

新增 `AuthorizationExplanationService`，输入：

```text
subject
business_application
capability
environment/base/workshop
```

输出仅包含：

- 最终 allow/deny；
- 决策阶段；
- 来源角色安全摘要；
- 应用、能力和明确数据范围来源；
- 被 Agent/平台上限阻止的原因类型；
- 高级拒绝或旧策略兼容标记；
- 相关 policy/grant ID 的安全引用。

不返回 condition JSON、secret、Token、连接信息、消息正文或工具响应。解释 API 使用与真实 evaluator 相同的纯决策组件，禁止复制一套只供 UI 的近似算法。

### 11. 授权在创建、执行、能力调用和投递四个阶段重新校验

业务应用 code、publication 和授权上下文必须持久化到 job；新 job 不只依赖易变的 routing JSON。授权检查位置：

```text
Channel/Trigger → 创建前校验
RabbitMQ Worker → PENDING 转 RUNNING 前校验
Tool Gateway    → 每次能力调用前校验
Delivery Worker → 发送业务结果前校验
```

Worker 前拒绝是非重试权限失败，不调用模型。执行中权限变化阻止下一次工具调用，不访问数据源。投递前权限变化时不发送业务结果，只尝试向原 reply route 发送固定中文安全通知；通知失败不得回退其它目标。job 可以保持执行成功，但 delivery attempt 标记 `BLOCKED_BY_AUTHORIZATION` 或等价独立状态。

第一版不增加授权缓存，关键检查直接读取 PostgreSQL 事实，确保立即生效。若后续引入缓存，必须由授权区 revision 参与 key 并主动失效。

### 12. 前端按权限目录渲染，但不把隐藏视为安全边界

导航调整为：

```text
用户与外部身份
├── 人员管理
├── 角色与授权
└── 未绑定钉钉用户
```

角色列表分为系统角色、自定义角色和高级授权例外。详情提供基本信息、成员、管理后台能力、业务应用与数据范围、有效权限预览和操作记录。

管理能力使用模块化复选框；业务范围使用：

```text
业务应用
  ├── 中文业务能力
  └── local
      └── 基地
          └── 车间
```

页面只显示当前 principal 有权查看的资源和动作；无权区域只读或隐藏。所有 API 仍独立鉴权。高风险权限不可跨模块一键全选，提交前要求二次确认和变更原因。所有用户可见提示和错误使用中文。

### 13. 数据库 migration 只做加法和安全回填

本 change 的 migration 只允许：

- 为角色和成员增加新列；
- 创建新角色管理能力、应用访问、能力和明确 scope 表；
- 创建必要唯一约束和索引；
- 为 `platform-admin` 增加受保护系统属性；
- 对现有行填充中性 revision/default，不删除或改写其授权含义。

不得自动把旧项目、Agent 或平台 grant 猜测成新业务应用授权。旧策略在兼容模式读取。实际人员、身份、角色和授权清理必须等待独立重置 change。

## Risks / Trade-offs

- [统一角色同时包含两类权限，配置容易变复杂] → 页面分授权区、分区 revision、模板和安全预览；不同管理员只能编辑被委派区域。
- [业务应用授权与旧 project/agent 策略并存产生双重语义] → 明确 compatibility/strict 模式、显式 deny 永远优先、trace 标记旧兼容来源，后续独立 change 完成清理和严格切换。
- [平台管理员 special-case 被误用于业务数据] → special-case 仅应用于后端注册的管理能力目录，业务 evaluator 不识别管理旁路。
- [“当前全部”展开大量 scope 行] → 使用批量插入、唯一索引和按 application/role 的组合索引；当前只有 local 环境，数据量可控。
- [授权即时生效增加数据库读取] → 第一版不缓存以保证正确性；通过批量 principal/scope 查询和索引控制开销，后续缓存必须 revision-aware。
- [投递前撤权导致 job 成功但用户收不到结果] → 区分执行状态和投递授权状态，发送固定安全通知并在运行记录中明确说明。
- [服务账号被加入复合管理角色] → 保存角色管理能力和成员变更时双向校验，存在服务账号成员时禁止添加管理能力，包含管理能力时禁止添加服务账号。
- [跨授权区并发产生解释瞬时变化] → 每个区独立原子提交；解释返回各区 revision，运行时始终按数据库当前事实决策。
- [能力目录新增项造成既有自定义角色权限缺失] → 自定义角色默认 fail closed，UI 显示新增未配置权限；只有受保护 `platform-admin` 自动拥有未来管理能力。

## Migration Plan

1. 增加加法 migration 和 repository，回填角色 origin/protected 与各授权区 revision，不改变旧授权行为。
2. 扩展管理能力目录和 `/api/admin` typed catalog、角色分区、成员批量、解释 API；保留旧管理 API 只读兼容，禁止新 UI 直接写原始策略。
3. 实现应用访问聚合、明确 scope 表、授权 evaluator 和 compatibility/strict 双模式，默认 compatibility。
4. 把业务应用上下文持久化到新 job，接入创建前、Worker 前、工具前和投递前重新校验。
5. 实现前端角色列表/详情、人员角色面板、钉钉绑定初始角色、动态导航和能力勾选。
6. 使用表驱动测试验证管理能力矩阵、角色并集/deny、成员过期、委派边界、最后管理员保护、分区并发和原子回滚。
7. 构建并重建相关容器，在 compatibility 模式验证旧链路不回归；在受控测试数据上启用 strict 模式验证新角色链路。
8. 用真实钉钉私聊和群聊验证身份绑定加初始角色、Runtime → Inbox → Outbox → Job → Worker → Tool → Delivery，并验证撤权后的执行和投递拦截。
9. 本 change 验收后，才创建和执行 `reset-identity-and-authorization-bootstrap`，完成旧人员/授权清理、新管理员初始化和严格模式切换。

回滚时先把授权模式切回 compatibility，回退前端入口和新 evaluator 调用；加法表和审计保留。不得通过删除新表或恢复旧数据库覆盖掉期间产生的授权审计。

## Open Questions

- 无。产品与安全决策已在本 change 提案前逐项确认；一次性身份与授权重置的实现细节属于后续独立 change。
