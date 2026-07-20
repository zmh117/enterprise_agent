## ADDED Requirements

### Requirement: 管理员可以管理 Webhook Trigger 草稿和发布版本
系统 SHALL 为 Webhook Trigger 保存定义、可编辑草稿 revision、校验结果、不可变 publication、当前 publication 指针和回滚历史，并 MUST 使用 expected revision 防止并发覆盖。

#### Scenario: 管理员保存新的草稿
- **WHEN** 具有 Webhook 编辑权限的管理员提交合法配置和当前 expected revision
- **THEN** 系统创建新的草稿 revision、记录配置 hash 和审计事件，且不改变运行中的 publication

#### Scenario: 两个管理员并发编辑
- **WHEN** 后提交者使用已经过期的 expected revision 保存
- **THEN** 系统返回版本冲突并要求刷新，不覆盖较新的草稿

#### Scenario: 管理员回滚 Trigger
- **WHEN** 具有发布权限的管理员选择历史有效 publication 回滚
- **THEN** 系统原子切换当前 publication 指针并保留全部历史快照

### Requirement: Trigger 发布前必须执行完整安全校验
系统 SHALL 在发布前校验 adapter schema、认证 secret reference、服务账号、Agent publication、routing 约束、来源 Connector、固定 Delivery、幂等和限流配置，任何依赖无效时 MUST 拒绝发布。

#### Scenario: 发布完整有效的 Grafana Trigger
- **WHEN** 草稿引用启用的 ingress Connector、可解析 secret、启用服务账号、默认诊断 Agent publication 和允许的钉钉 Delivery
- **THEN** 系统创建不可变 Trigger publication并记录 revision、schema version、config hash 和发布人

#### Scenario: 发布缺少认证 secret 的 Trigger
- **WHEN** 草稿选择 Bearer 或 HMAC 认证但 secret reference 为空或不可解析
- **THEN** 系统返回字段级校验错误且不创建 publication

#### Scenario: 发布越界 routing 映射
- **WHEN** `project_code`、`environment`、`base` 或 `workshop` 使用 payload 提取但没有非空 allowlist
- **THEN** 系统拒绝发布并指出无界 routing 字段

### Requirement: 第一版支持 Grafana Alertmanager 和通用 JSON 模板
系统 SHALL 提供 `grafana_alertmanager_v1` 和 `generic_json_v1` 两种 typed Trigger schema，并 MUST 拒绝未知 schema version 或包含脚本执行能力的配置。

#### Scenario: 创建 Grafana Trigger
- **WHEN** 管理员选择 Grafana Alertmanager 模板
- **THEN** 页面提供 status、groupKey、labels、annotations、routing 和 firing-only 的类型化配置

#### Scenario: 创建通用 JSON Trigger
- **WHEN** 管理员选择通用 JSON 模板
- **THEN** 页面允许用受限 JSON Pointer 和声明式条件配置事件 ID、消息字段、过滤和受控 routing

#### Scenario: 配置可执行模板
- **WHEN** 草稿包含 JavaScript、Python、Shell、任意函数调用或未支持模板语法
- **THEN** 系统拒绝保存或校验该执行性配置

### Requirement: 管理端提供无副作用的报文预览
系统 SHALL 允许授权管理员提交有界测试 JSON，并返回认证之外的映射、过滤、routing、消息、幂等键、固定 Agent 和 Delivery 安全预览；预览 MUST NOT 创建 Webhook event、Agent job、工具调用或外部投递。

#### Scenario: 预览 firing 告警
- **WHEN** 管理员对未发布或已发布 revision 提交测试 Grafana firing payload
- **THEN** 系统返回标准化结果和将使用的固定配置摘要，不触发 Agent

#### Scenario: 预览 resolved 告警
- **WHEN** 管理员提交 Grafana resolved payload
- **THEN** 系统返回 `IGNORED` 过滤结果并说明不会创建 job

### Requirement: Web UI 管理 Trigger 和事件历史
系统 SHALL 提供 Webhook 列表、创建/编辑、校验、发布、回滚、public ID 轮换、预览和事件历史页面，并 MUST 根据独立管理 action 控制可见操作。

#### Scenario: 只读管理员查看事件
- **WHEN** 当前管理员只有 Webhook 查看权限
- **THEN** 页面允许查看脱敏配置和事件状态，但隐藏编辑、发布、轮换和 secret 操作

#### Scenario: 第一版选择 Agent
- **WHEN** 管理员编辑 Trigger 的 Agent 绑定
- **THEN** UI 只展示默认诊断 Agent 的有效 publication，后端快照仍保存通用 Agent code 和 publication ID

### Requirement: 管理 API 和页面不得泄漏敏感材料
系统 SHALL 只返回 secret reference、凭证状态和脱敏摘要，MUST NOT 返回 Bearer token、HMAC secret、完整 Webhook URL 中的敏感参数、密码材料或原始测试 payload。

#### Scenario: 管理员读取 Trigger 详情
- **WHEN** 管理员打开认证配置
- **THEN** 页面仅显示认证类型、secret reference 和是否可解析，不显示 secret value

#### Scenario: 管理员轮换 public ID
- **WHEN** 授权管理员确认轮换公共入口标识
- **THEN** 系统生成新的不可预测 public ID、立即拒绝旧 ID 并记录审计事件
