## MODIFIED Requirements

### Requirement: Webhook Trigger 使用真实草稿和不可变发布
管理端 SHALL 提供 Grafana Alertmanager 和通用 JSON Trigger 的创建、编辑、验证、发布、启停、回滚、public ID/凭据轮换与事件历史。草稿使用 revision，发布固定 adapter、源 Connector、执行用户与认证配置；Agent 与投递由业务应用引用固定；保存草稿不改变运行版本。

#### Scenario: 两人并发修改 Trigger
- **WHEN** 后提交者使用过期 expected revision
- **THEN** 返回版本冲突，不覆盖新草稿或运行 Publication

#### Scenario: 发布依赖缺失
- **WHEN** Connector、execution_user_id 对应的启用 human 用户、已配置的 Bearer Secret 或 schema 不可用
- **THEN** 返回中文字段错误，不创建 Publication

#### Scenario: 无副作用报文预览
- **WHEN** 管理员提交示例 JSON 测试映射
- **THEN** 只返回有界脱敏映射预览，不持久化原 body、不创建 Job、不发送 Delivery

### Requirement: 公共 Webhook 只接受有界 JSON 和唯一强 Bearer
公共入口 SHALL 通过不可预测 public ID 找到启用 Trigger 的有效 Publication，检查来源 Connector 和启用执行用户，并限定 Content-Type、UTF-8 body 大小、JSON 深度与集合数量。认证支持明确的 none 或 bearer_v1；none 不引用凭据，bearer_v1 使用唯一且达到代码强度的受管 Token 并常量时间比较，缺失、弱值、不可解析或错误认证失败关闭。

#### Scenario: 使用合法标准 Bearer
- **WHEN** 有效 publication 收到符合大小和结构上限的 JSON 与匹配的 `Authorization: Bearer`
- **THEN** 继续映射和接收，不把认证成功当作业务授权成功

#### Scenario: 明确免鉴权配置
- **WHEN** 发布配置认证为 none 且不引用凭据
- **THEN** 接收无需 Authorization 请求头的有界 JSON，仍执行执行用户、应用和资源权限检查

#### Scenario: 旧 Header 或其他认证模式
- **WHEN** Bearer 端点的请求只提供 `X-Grafana-Token`，或配置 HMAC、timestamp、nonce 认证
- **THEN** 拒绝，不进入匿名或旧 Header 翻译兼容路径；事件去重不能表述为独立防重放认证

#### Scenario: 未知或轮换后的 public ID
- **WHEN** public ID 不存在或已失效
- **THEN** 返回统一安全未找到结果，不暴露历史配置或 Secret

### Requirement: Webhook 映射不能覆盖授权和目标事实
Webhook SHALL 使用固定通用 JSON 或 Grafana Alertmanager adapter 生成 Channel message；配置不支持自定义 JSON Pointer、条件或模板。通用 JSON 只读取 id 和 message，routing 从命中的业务应用派生，文本始终是不可信外部数据。payload 不得控制执行用户、Agent、Tool、Connector、Secret、Delivery endpoint 或扩大业务范围。

#### Scenario: 通用 JSON 必填路径缺失
- **WHEN** 通用 JSON 的 id 或 message 缺失或类型不匹配
- **THEN** 保存安全映射失败状态，不创建 Job

#### Scenario: payload 声明其他应用或目标
- **WHEN** 外部 body 含任意 actor、Agent、Connector 或投递字段
- **THEN** 规范化仅使用声明字段与冻结控制事实，其余排除或拒绝；不得把完整原 payload 放入 Session、Job 或 Prompt

### Requirement: Webhook 持久受理与业务授权分阶段完成
接收服务 SHALL 在认证、结构、映射、过滤和限流通过后，用事务保存 Event 与 Outbox，成功后返回 `202 Accepted`。该响应只证明持久受理。Dispatcher SHALL 使用接收时固定的 Trigger/Agent Publication 与执行用户，并重新检查启停、完整性和 Channel/应用授权后创建 Job；不得把 Inbox 接受等同于业务授权已通过。

#### Scenario: 排队期间发布新 Trigger
- **WHEN** 已接受 Event 等待分发而管理员发布新版本
- **THEN** Dispatcher 仍读取 Event 固定的 Trigger/Agent Publication；若与当前活动应用路由冲突则安全失败，不静默替换版本

#### Scenario: 排队期间执行用户停用
- **WHEN** Dispatcher 处理已接受事件时账号或 Trigger 已停用
- **THEN** 记录分发失败，不创建 Job

#### Scenario: Broker 故障或重复消息
- **WHEN** Outbox 首次发送失败或 dispatcher 重复收到已有 Job 的 Event
- **THEN** 通过有界恢复重试发布或返回幂等成功，不创建第二个 Job

#### Scenario: 排队期间重新绑定执行用户
- **WHEN** 原事件已受理后 Webhook 发布绑定另一用户
- **THEN** 原事件仍使用接收时冻结的用户，并验证与其固定发布一致，不能替换成新用户
