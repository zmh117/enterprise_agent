## RENAMED Requirements

- FROM: `### Requirement: 公共 Webhook 只接受有界 JSON 和唯一强 Bearer`
- TO: `### Requirement: 公共 Webhook 接受有界 JSON 和可选 Bearer`

## MODIFIED Requirements

### Requirement: 公共 Webhook 接受有界 JSON 和可选 Bearer
公共入口 SHALL 通过不可预测 public ID 找到启用 Trigger 的有效 Publication，检查来源 Connector 和启用的人员执行用户，并限定 Content-Type、UTF-8 body 大小、JSON 深度与集合数量。认证 SHALL 支持显式 `none` 或 `bearer_v1`。Bearer binding SHALL 使用唯一受管 Token，允许 1–4096 字节、不含空白的可打印 ASCII 字符，不要求至少 32 个字符或熵阈值，并进行常量时间精确比较；配置 Bearer 后缺失、格式非法、不可解析或错误认证 MUST 失败关闭，不得自动降级免鉴权。管理端 SHALL 不再显示 32 字符或高熵的强制要求。

#### Scenario: 使用合法标准 Bearer
- **WHEN** 有效 publication 收到符合大小和结构上限的 JSON 与匹配的 `Authorization: Bearer`
- **THEN** 继续映射和接收，不把认证成功当作业务授权成功

#### Scenario: 使用短 Bearer Token
- **WHEN** 管理员绑定非空、格式合法、少于 32 字符的唯一受管 Token
- **THEN** 校验、发布及渠道就绪检查接受该凭据，公共入口允许携带匹配 Bearer 的请求

#### Scenario: Bearer 凭据或请求无效
- **WHEN** Bearer 凭据为空、包含空白或不可打印字符、超过 4096 字节、无法解析，或请求头缺失及不匹配
- **THEN** 对应校验或鉴权失败，且不得转为免鉴权

#### Scenario: 显式免鉴权
- **WHEN** 有效 Publication 的认证为 `none` 且凭据引用为空
- **THEN** 公共入口不要求 Authorization 请求头，仍执行应用路由与执行用户权限检查

#### Scenario: 旧 Header 或其他认证模式
- **WHEN** Bearer 请求只提供 `X-Grafana-Token`，或配置 HMAC、timestamp、nonce 认证
- **THEN** 拒绝，不进入匿名或旧 Header 翻译兼容路径；事件去重不能表述为独立防重放认证

#### Scenario: 未知或轮换后的 public ID
- **WHEN** public ID 不存在或已失效
- **THEN** 返回统一安全未找到结果，不暴露历史配置或 Secret
