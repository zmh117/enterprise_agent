## ADDED Requirements

### Requirement: 管理端只开放两类受管入口 Channel
系统 SHALL 在本阶段只允许管理员创建和管理 `WEBHOOK`、`DINGTALK_APP_ROBOT` 两类入口 Channel，并拒绝通过该管理入口创建其他提供者类型。

#### Scenario: 创建钉钉应用机器人
- **WHEN** 有 Channel 管理权限的管理员提交应用名称、Client ID、Client Secret 和聊天策略
- **THEN** 系统创建 `dingtalk_enterprise_stream` Connector、加密保存 Secret，并返回不含明文凭据的 Channel

#### Scenario: 创建受管 Webhook
- **WHEN** 有 Channel 管理权限的管理员提交受支持的 Webhook 配置
- **THEN** 系统委托现有受管 Webhook 服务创建配置，并在统一 Channel 目录中返回 `WEBHOOK` 项

#### Scenario: 提交不支持的 Channel 类型
- **WHEN** 管理员通过该接口提交 email、WeCom、任意 HTTP 或其他未开放提供者
- **THEN** 系统返回字段级校验错误，且不创建 Connector、Secret 或 Trigger

### Requirement: Channel 管理使用乐观并发和明确生命周期
系统 SHALL 为 Channel 配置暴露 revision，并要求更新、启用、停用、重连和删除操作携带预期 revision。

#### Scenario: 使用当前 revision 更新
- **WHEN** 管理员使用当前 expected revision 更新 Channel 配置
- **THEN** 系统追加配置修订或递增 Connector revision，并返回更新后的状态

#### Scenario: 使用过期 revision 更新
- **WHEN** 管理员使用已过期 expected revision 修改 Channel
- **THEN** 系统拒绝写入并返回 revision conflict，不覆盖其他管理员的修改

#### Scenario: 删除仍在使用的 Channel
- **WHEN** 管理员删除仍被已发布或活动 Business Application Trigger 引用的 Channel
- **THEN** 系统拒绝删除并返回安全的引用摘要

### Requirement: 钉钉 Client Secret 由受管 Secret 服务保存
系统 SHALL 接受钉钉 Client Secret 的一次性明文输入，通过现有 AES-GCM 受管 Secret 保存，并且 MUST NOT 在查询响应、审计、日志或错误中返回原值。

#### Scenario: 首次保存 Secret
- **WHEN** 管理员创建钉钉应用机器人并输入 Client Secret
- **THEN** 系统创建受管 Secret 版本、把 Secret reference 绑定到 Connector，并只返回 `secret_configured=true` 和脱敏摘要

#### Scenario: 编辑时留空 Secret
- **WHEN** 管理员编辑钉钉应用机器人但未输入新 Secret
- **THEN** 系统保留现有 Secret 版本，不清空凭据

#### Scenario: 轮换 Secret
- **WHEN** 管理员输入新 Secret 并提交当前 revision
- **THEN** 系统创建新的 Secret 版本、递增 Connector revision，并使 Runtime 只重建该 Connector 的 Client

### Requirement: 管理 API 区分期望状态与实际状态
系统 SHALL 同时返回 Channel 的配置启用状态和 Runtime 观测状态，不得把管理员的启用意图显示为已连接。

#### Scenario: 已启用但认证失败
- **WHEN** Channel 已启用而 Runtime 上报 `AUTH_FAILED`
- **THEN** API 返回 desired status 为 enabled、observed status 为 AUTH_FAILED 和脱敏错误摘要

#### Scenario: 心跳过期
- **WHEN** 最近一次 Runtime 心跳超过服务端配置的过期阈值
- **THEN** API 将有效运行状态计算为 STALE，即使数据库上一次观测为 READY

### Requirement: Trigger 可选 Channel 目录只返回合格入口
系统 SHALL 提供供 Business Application 使用的 Channel 目录，并只把已启用、允许 ingress 且支持目标 Trigger 类型的 Channel 标记为可选。

#### Scenario: 查询钉钉群聊可选项
- **WHEN** Business Application 查询 `dingtalk_group` Trigger 的 Channel 目录
- **THEN** 系统只返回已启用且 ingress-eligible 的钉钉应用机器人

#### Scenario: 查询 Webhook 可选项
- **WHEN** Business Application 查询 `webhook` Trigger 的 Channel 目录
- **THEN** 系统只返回已启用且已发布必要入口配置的受管 Webhook

#### Scenario: Channel 已停用
- **WHEN** Channel 被停用或不允许 ingress
- **THEN** 系统在管理列表中保留该记录，但不得将其标记为新的 Trigger Binding 可选项

### Requirement: Channel 管理操作受 RBAC 和审计约束
系统 SHALL 对读取、创建、编辑、启停、重连和删除执行服务端 RBAC，并记录不包含 Secret 的审计事件。

#### Scenario: 有权限管理员执行重连
- **WHEN** 具备 Channel manage 权限的管理员请求重连钉钉应用机器人
- **THEN** 系统递增 Connector revision、记录 actor 和 Connector ID，并且不记录凭据

#### Scenario: 无权限用户修改 Channel
- **WHEN** 用户没有 Channel manage 权限却提交写操作
- **THEN** 系统拒绝操作、保留原配置并记录拒绝审计
