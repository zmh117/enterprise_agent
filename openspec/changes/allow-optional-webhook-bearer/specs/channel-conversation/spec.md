## RENAMED Requirements

- FROM: `### Requirement: 公共 Webhook 只接受有界 JSON 和唯一强 Bearer`
- TO: `### Requirement: 公共 Webhook 接受有界 JSON 和可选 Bearer`

## MODIFIED Requirements

### Requirement: Webhook Trigger 使用真实草稿和不可变发布
管理端 SHALL 提供 Grafana Alertmanager 和通用 JSON Trigger 的创建、编辑、验证、发布、启停、回滚、public ID/凭据轮换与事件历史。草稿使用 revision，发布固定 adapter、源 Connector、服务账号、Agent Publication、routing、Delivery、幂等和限流配置；保存草稿不改变运行版本。

#### Scenario: 两人并发修改 Trigger
- **WHEN** 后提交者使用过期 expected revision
- **THEN** 返回版本冲突，不覆盖新草稿或运行 Publication

#### Scenario: 发布依赖缺失
- **WHEN** Connector、服务账号、固定 Agent、Delivery、已配置的 Bearer Secret 或 schema 不可用
- **THEN** 返回中文字段错误，不创建 Publication

#### Scenario: 无副作用报文预览
- **WHEN** 管理员提交示例 JSON 测试映射
- **THEN** 只返回有界脱敏映射预览，不持久化原 body、不创建 Job、不发送 Delivery

### Requirement: 公共 Webhook 接受有界 JSON 和可选 Bearer
公共入口 SHALL 通过不可预测 public ID 找到启用 Trigger 的有效 Publication，检查来源 Connector 和启用服务账号，并限定 Content-Type、UTF-8 body 大小、JSON 深度与集合数量。认证 SHALL 支持显式 `none` 和 `bearer_v1`。管理员留空凭据可保存、校验和发布为 `none`；该模式接收时无需 Authorization。非空引用采用 `bearer_v1`，每个 binding 使用唯一且至少符合代码强度要求的受管 Token，进行常量时间比较；该模式缺失请求凭据、弱值、不可解析或错误认证必须失败关闭。模式 MUST 随 Publication 冻结，保存草稿不改变当前入口。未知或缺失认证模式不得隐式降级。

#### Scenario: 使用合法标准 Bearer
- **WHEN** 有效 publication 收到符合大小和结构上限的 JSON 与匹配的 `Authorization: Bearer`
- **THEN** 继续映射和接收，不把认证成功当作业务授权成功

#### Scenario: 旧 Header 或其他认证模式
- **WHEN** Bearer 模式请求只提供 `X-Grafana-Token`，或配置 HMAC、timestamp、nonce 认证
- **THEN** 拒绝，不进入匿名或旧 Header 翻译兼容路径；事件去重不能表述为独立防重放认证

#### Scenario: 未知或轮换后的 public ID
- **WHEN** public ID 不存在或已失效
- **THEN** 返回统一安全未找到结果，不暴露历史配置或 Secret

#### Scenario: 凭据留空并发布免鉴权入口
- **WHEN** 管理员留空凭据引用并完成有效发布、启用和应用路由激活
- **THEN** 系统 SHALL 接受不带 Authorization 的有界 JSON，并继续校验来源、服务账号、业务角色、活动应用路由、限流与去重

#### Scenario: 受保护入口修改草稿
- **WHEN** 已发布 Bearer 入口的草稿清空凭据，尚未发布
- **THEN** 当前入口 MUST 继续要求 Bearer，直到新版本发布

## ADDED Requirements

### Requirement: Webhook 配置页展示匹配配置的 HTTP 示例
管理端 SHALL 展示使用当前 public ID、POST 和 application/json 的 curl 示例，区分通用 JSON 与 Grafana 标准报文。依据当前编辑配置是否填写凭据展示或省略 Authorization 头。Token MUST 使用占位符，不读取或展示真实值。页面 SHALL 解释事件 ID 的去重用途、替换服务地址、发布启用和应用激活要求，以及 202 只代表受理。

#### Scenario: 免鉴权示例
- **WHEN** 凭据引用为空
- **THEN** 展示不含 Authorization 的 curl，URL 包含当前 Webhook public ID

#### Scenario: Bearer 示例
- **WHEN** 管理员填写凭据引用
- **THEN** 示例包含 Bearer Token 占位符，并说明调用方填写 Token 原文、变更发布后生效
