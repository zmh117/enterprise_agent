# deepseek-model-connection-setup Specification

## Purpose
TBD - created by archiving change redesign-deepseek-model-connection-setup. Update Purpose after archive.
## Requirements
### Requirement: 管理Web必须提供连续的DeepSeek模型连接配置向导
系统 SHALL 在默认 Agent Profile 的“模型与连接”区域提供单一连续向导，依次完成 DeepSeek Anthropic Base URL 与 Credential 输入、模型发现、模型映射、真实配置测试和最终保存。系统 MUST NOT 再要求管理员通过独立的连接 revision 保存、Credential 弹窗和已保存版本测试完成一次配置。

#### Scenario: 首次配置模型连接
- **WHEN** 具有 Agent 编辑与 Secret 管理权限的管理员打开尚未配置 Credential 的默认模型连接
- **THEN** 页面按 URL 与 Key、模型发现、模型映射、配置测试和最终保存的顺序引导操作
- **AND** 在最终保存成功前不把连接显示为 ready

#### Scenario: 输入变化使下游结果失效
- **WHEN** 管理员在模型发现后修改 Base URL 或 Credential，或者在配置测试后修改任一模型映射或 effort
- **THEN** 页面清除所有受影响的发现或测试结果
- **AND** 管理员必须从相应步骤重新检测

### Requirement: 系统必须只发现DeepSeek官方服务的模型
系统 SHALL 只接受满足部署 allowlist 的 DeepSeek 官方 HTTPS Anthropic Base URL，并 MUST 通过移除末尾 `/anthropic`、追加 `/models` 确定性派生模型发现 URL。系统 MUST 拒绝 userinfo、query、fragment、非 443 端口、未批准 host、非法 path、redirect，以及解析到回环、链路本地、私网或保留 IP 的目标。

#### Scenario: 从官方Anthropic URL发现模型
- **WHEN** 管理员提交 `https://api.deepseek.com/anthropic` 和有效 Credential
- **THEN** 系统请求同一官方服务的 `https://api.deepseek.com/models`
- **AND** 返回去重、受限且不含 Credential 的模型 ID 列表

#### Scenario: 拒绝第三方或自定义发现地址
- **WHEN** 管理员提交第三方 Anthropic-compatible host、自定义模型列表 URL 或不符合规则的 Base URL
- **THEN** 系统在外部请求前以稳定字段错误拒绝
- **AND** 不尝试猜测第三方 `/models` 路径

#### Scenario: 模型列表响应不安全
- **WHEN** DeepSeek 模型列表为空、格式错误、超出响应大小或模型数量上限
- **THEN** 系统返回稳定安全的模型发现错误
- **AND** 不返回上游响应正文或内部解析异常

### Requirement: 模型发现和草稿测试必须无持久化副作用
系统 SHALL 允许使用本次提交的 API Key 或当前有效 encrypted DB Credential 执行模型发现与草稿配置测试。发现和测试动作 MUST NOT 创建或更新 Secret、Secret version、模型连接 revision、Agent 草稿或 Publication，且 MUST NOT 把 API Key 写入日志、审计 payload、查询缓存或响应。

#### Scenario: 使用新Key发现失败
- **WHEN** 管理员提交新 API Key 但 DeepSeek 拒绝鉴权或请求超时
- **THEN** 系统返回脱敏错误并保持数据库不变
- **AND** 不创建孤立 Secret 或 rotation-required revision

#### Scenario: 沿用已有Credential执行发现
- **WHEN** 当前模型连接绑定可用 Credential 且管理员选择沿用
- **THEN** 服务端内部解析 active Secret 完成发现
- **AND** 前端仍只看到 configured 状态、脱敏摘要和模型列表

#### Scenario: 关闭向导清除明文
- **WHEN** 管理员关闭、离开或成功完成配置向导
- **THEN** 前端立即清空 API Key input state 和 mutation variables
- **AND** 不把该值写入 URL、local storage、session storage 或 TanStack Query data

### Requirement: 模型映射必须由当前发现结果驱动
系统 SHALL 要求主模型选择自当前发现结果，并 SHALL 允许 Opus、Sonnet、Haiku 和 Subagent 映射选择发现模型或继承主模型。最终保存前系统 MUST 把继承项规范化为显式主模型，并 MUST 重新确认所有模型仍在最新发现列表中。

#### Scenario: 配置不同模型映射
- **WHEN** 管理员从发现列表分别选择主模型、Opus、Sonnet、Haiku 和 Subagent 模型
- **THEN** 页面显示每个映射的明确选择
- **AND** 草稿测试与最终连接 revision 使用同一组规范化模型

#### Scenario: 默认映射继承主模型
- **WHEN** 管理员把任一默认模型或 Subagent 模型设为“继承主模型”
- **THEN** 系统在测试和保存前使用主模型补齐
- **AND** 保存的非敏感 config 包含补齐后的显式值

#### Scenario: 旧模型不再可用
- **WHEN** 当前历史 revision 的模型不在最新发现列表中
- **THEN** 页面显示旧值和不可用警告但不修改历史 revision
- **AND** 管理员必须重新选择可用模型后才能保存新 revision

### Requirement: 保存前必须通过真实Claude Agent SDK配置测试
系统 SHALL 使用临时非敏感配置和本次 Credential 来源，通过与生产 Job 相同的 Claude Agent SDK 兼容路径执行无 Tool、无 MCP、单轮、短超时测试。测试 MUST 使用所选主模型，MUST NOT 接受任意 Prompt，并 MUST NOT 返回模型响应正文、SDK stderr、Credential 或请求 header。

#### Scenario: 草稿配置测试成功
- **WHEN** 规范化 URL、Credential 和所选主模型可以通过 Claude Agent SDK 完成最小探测
- **THEN** 系统返回 provider host、模型、耗时和成功状态
- **AND** 页面允许进入最终保存步骤

#### Scenario: 发现成功但模型调用失败
- **WHEN** `/models` 返回所选模型但 Claude Agent SDK 认证、模型调用或协议兼容测试失败
- **THEN** 系统返回稳定安全错误并禁止最终保存
- **AND** 数据库与 active Secret 保持不变

### Requirement: 最终配置必须原子保存Secret和连接revision
系统 SHALL 提供一个带 `expected_revision` 的原子配置动作。该动作 MUST 在数据库事务外重新执行模型发现与真实配置测试，在提交前再次校验 revision，并 MUST 在同一数据库 unit of work 中创建或轮换 encrypted DB Secret、追加一个 ready 模型连接 revision、更新 current revision/status 和写入脱敏审计。任一步失败时 MUST 不产生部分写入。

#### Scenario: 首次原子配置成功
- **WHEN** 未绑定 Credential 的连接提交有效 URL、API Key、模型映射和当前 expected revision
- **THEN** 系统创建 encrypted DB Secret 并追加绑定该 Secret 的 ready revision
- **AND** 响应只返回公共连接状态和脱敏 Credential 摘要

#### Scenario: 最终验证失败
- **WHEN** 最终保存时重新发现的模型列表不再包含所选模型或 SDK 测试失败
- **THEN** 系统不创建 Secret、Secret version 或连接 revision
- **AND** 当前连接状态和 revision 保持不变

#### Scenario: 保存期间发生并发修改
- **WHEN** 外部测试完成后连接 revision 已不再等于 expected revision
- **THEN** 系统返回包含当前 revision 的 409
- **AND** Secret 与连接 revision 均不发生部分更新

### Requirement: 原子配置必须支持Credential沿用、轮换和缺失恢复
系统 SHALL 允许新 revision 沿用当前可用 Credential，或在管理员提交新 API Key 时轮换同一受管 Credential。当前绑定缺失、停用、不可解析或处于 rotation-required 状态时，系统 MUST 要求新 API Key。确定性 Secret code 已存在但未绑定时，系统 MUST 仅在其所有权 metadata 明确属于同一 model connection 时允许轮换并重新绑定。

#### Scenario: 沿用当前有效Credential
- **WHEN** 管理员只修改模型映射并选择沿用当前有效 Credential
- **THEN** 新 revision 继续绑定同一 Secret 身份
- **AND** 系统不创建新的 Secret version

#### Scenario: 轮换当前Credential
- **WHEN** 管理员提交新的 API Key 并完成最终配置
- **THEN** 系统创建新的 active Secret version并让新 revision 保持稳定 Credential 身份
- **AND** 旧明文和旧 active version不再解析

#### Scenario: 恢复未绑定连接
- **WHEN** 当前连接为 rotation-required 且没有 Secret 绑定，管理员提交新 API Key
- **THEN** 系统创建或安全重新绑定属于该连接的受管 Secret
- **AND** 连接在同一事务中进入 ready

#### Scenario: 拒绝Secret所有权冲突
- **WHEN** 确定性 Secret code 已由其他资源或其他 model connection 管理
- **THEN** 系统失败关闭并返回 Credential 所有权冲突
- **AND** 不轮换、不覆盖且不重新绑定该 Secret

### Requirement: 模型连接配置操作必须授权、限流、审计和脱敏
系统 SHALL 要求 Agent 编辑权限与 Secret 管理权限才能执行 discover、test-draft 和 configure，并 MUST 对外部探测动作实施用户与连接维度限流。系统 MUST 使用稳定中文错误区分 URL、鉴权、发现、空模型、模型不可用、SDK 测试、超时、并发和所有权冲突；审计和运行输出 MUST 不包含 API Key、Authorization header、Secret ref、模型响应正文或完整上游错误。

#### Scenario: 无Secret权限执行模型发现
- **WHEN** 只有 Agent 编辑权限的用户提交 discover、test-draft 或 configure
- **THEN** 系统在任何 Secret 解析或外部网络请求前拒绝
- **AND** 不产生模型调用费用或配置写入

#### Scenario: 探测请求超过限额
- **WHEN** 同一用户或连接在限流窗口内超过允许的发现或测试次数
- **THEN** 系统返回稳定限流错误且不访问 DeepSeek
- **AND** 审计只记录 actor、连接 code、动作和安全结果

#### Scenario: 安全错误投影
- **WHEN** DeepSeek 或 Claude Agent SDK 返回包含请求 header、Key、响应正文或内部异常的失败
- **THEN** API 只返回稳定错误码和中文安全摘要
- **AND** 日志、审计和前端状态不包含敏感原文

