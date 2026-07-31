## Context

`add-agent-profile-model-connection-management` 已经提供追加式模型连接 revision、encrypted DB Secret 绑定、Claude Agent SDK 连接测试和 Agent Publication 固定连接版本的能力。当前管理页面却把操作拆成三个独立动作：

```text
保存连接 revision
        ↓
配置或轮换 API Key
        ↓
测试已保存 revision
```

每个写动作都会递增 `model_connection.revision`。连接保存成功后，前端查询失效和重新渲染之间存在窗口；如果管理员立即提交 Key，凭据接口可能仍携带旧 `expected_revision`，后端正确返回 409，但用户看到的是配置失败。这个问题不是单个按钮状态可以彻底解决的，因为当前交互本身要求用户跨多个资源版本完成一次配置。

本次范围已确认只支持 DeepSeek 官方服务。运行时继续使用 Anthropic-compatible URL 和 Claude Agent SDK；模型发现使用同一官方服务的 OpenAI-compatible `GET /models`。不为任意第三方 Provider 猜测模型发现路径。

必须保留以下边界：

- API Key 明文只在当前请求和前端临时表单状态中存在，不进入数据库非 Secret 字段、日志、审计、查询缓存、响应或错误详情。
- Agent Publication 继续固定非敏感连接 revision；本变更不重写历史 Publication，也不自动发布 Agent 或切换业务应用。
- URL、DNS、redirect、RBAC 和审计继续使用现有安全边界。
- 外部网络调用不得在数据库事务或行锁持有期间执行。

## Goals / Non-Goals

**Goals:**

- 把 URL、Credential、模型发现、模型映射、真实测试和最终保存组织成一个连续向导。
- 让模型字段由 DeepSeek 实时返回的可用模型驱动，不再要求管理员先猜模型名。
- 让探测和测试失败无持久化副作用。
- 用一个服务端原子配置动作创建或轮换 Secret 并追加 ready 连接 revision。
- 消除前端跨 revision 的保存竞态，并保留后端乐观并发保护。
- 支持首次配置、缺失 Credential 恢复、主动 Key 轮换和沿用已有有效 Credential。

**Non-Goals:**

- 不支持任意第三方 Anthropic-compatible 服务、自定义模型列表 URL 或 Provider 插件。
- 不增加 OpenAI Runtime Adapter；OpenAI-compatible `/models` 只用于 DeepSeek 模型发现。
- 不把发现到的完整模型列表持久化为连接 revision 或 Agent Publication。
- 不自动保存、校验或发布 Agent 草稿，不自动切换 Business Application。
- 不保留旧的三段式 Web 交互兼容。
- 不实现 HTTPS 部署、Master Key 轮换、HMAC Webhook 或其他平台安全扩展。

## Decisions

### 1. 使用单页状态机而不是独立Credential弹窗

连接编辑器使用以下状态：

```text
EDITING
  │ 检测凭据并获取模型
  ▼
DISCOVERED
  │ 选择模型映射
  ▼
MAPPED
  │ 测试当前配置
  ▼
TESTED
  │ 原子保存
  ▼
READY
```

Base URL、Credential 来源或 API Key 发生变化时，必须清除模型发现和测试结果并回到 `EDITING`。任一模型映射或 effort 发生变化时，必须清除测试结果并回到 `MAPPED`。关闭页面、切换 Agent、保存成功或组件卸载时必须清空 API Key。

选择状态机而不是修补弹窗 revision，是因为 URL、Key 和模型映射共同决定一个可用连接，用户需要看到它们之间的因果关系。独立弹窗会继续制造过期 props、重复错误区和不清晰的完成状态。

### 2. 从一个DeepSeek Anthropic URL确定性派生模型发现URL

用户只输入 Anthropic Base URL。服务端规范化后要求：

- scheme 为 `https`；
- host 精确为部署 allowlist 中的 `api.deepseek.com`；
- 端口为空或 `443`；
- 不含 userinfo、query 或 fragment；
- path 以单个 `/anthropic` 结尾。

模型发现 URL 通过移除末尾 `/anthropic` 并追加 `/models` 得到。例如：

```text
https://api.deepseek.com/anthropic
        ↓
https://api.deepseek.com/models
```

这样既支持当前官方 URL，又不会让前端额外输入可被滥用的探测地址。任意 redirect 均拒绝；DNS 结果继续拒绝回环、链路本地、私网和保留地址。

不采用“允许用户填写模型列表 URL”，因为它扩大 SSRF 面并引入两个 URL 漂移。不采用“对任意 Anthropic Provider 尝试 `/models`”，因为 Anthropic-compatible 协议没有统一模型列表契约。

### 3. 模型发现和草稿测试使用临时输入且不写数据库

新增三个管理动作：

```text
POST /api/admin/model-connections/{code}/discover
POST /api/admin/model-connections/{code}/test-draft
PUT  /api/admin/model-connections/{code}/configure
```

`discover` 接收 Base URL，以及“本次提交 API Key”或“沿用当前有效 Credential”二选一。服务端使用 Bearer Credential 请求派生的 `/models`，只返回：

```text
provider_host
normalized_base_url
models[]          # id 和安全显示名
duration_ms
credential_source # submitted 或 existing
```

响应体上限为 256 KiB，最多接受 200 个唯一模型，单个模型 ID 最长 200 字符；空列表、畸形 JSON、重复异常、超限响应和未知字段形态均返回稳定安全错误。

`test-draft` 接收同一临时 Credential 来源和完整非敏感模型配置，通过现有 Claude Agent SDK 执行无 Tool、无 MCP、单轮、短超时探测。它不接受任意 Prompt，也不返回模型正文。

两个动作都不得创建 Secret、Secret version、模型连接 revision 或审计中的敏感 payload。审计只记录 actor、连接 code、脱敏 host、模型、时长、结果和错误码。

### 4. 所有模型映射只能选择本次发现结果

主模型必须选择一个发现到的模型。Opus、Sonnet、Haiku 和 Subagent 映射允许选择发现模型或“继承主模型”；保存前把继承项规范化为显式主模型值。所有显式模型都必须仍存在于最终保存时重新获取的模型列表。

不提供任意文本模型 ID 作为常规入口。若旧 revision 的模型不在新列表中，页面以只读旧值和警告显示，但必须重新选择后才能完成新配置；历史 revision 和 Publication 保持不变。

### 5. 最终configure在服务端重新验证后原子提交

前端 `TESTED` 状态用于良好交互，但不能成为服务端信任边界。`configure` 必须：

1. 在外部 I/O 前读取连接并预检 `expected_revision`；
2. 在不持有数据库事务的情况下重新执行模型发现；
3. 校验所有选择模型仍在返回列表；
4. 使用所选主模型重新执行受限 Claude Agent SDK 测试；
5. 再次读取连接并校验 `expected_revision`；
6. 在同一数据库 unit of work 中创建或轮换 encrypted DB Secret、追加一个 `ready` 模型连接 revision、更新 current revision/status，并写入脱敏审计；
7. 返回新的公共 revision，不返回 Secret ID、ref、密文或明文。

最终保存重复一次外部测试会增加一次最小模型调用，但避免引入短期服务器会话、测试收据、Redis 状态或仅由前端保证的假验证。若任何外部校验失败，数据库没有写入；若校验后发生并发修改，事务返回 409，Secret 和 revision 均不得部分提交。

### 6. Secret创建、轮换和恢复遵循同一所有权规则

`configure` 的 Credential 规则：

- 首次配置、当前 revision 未绑定 Secret、Secret 记录缺失或状态不可用时，必须提交新 API Key。
- 当前绑定可用且用户选择沿用时，解析现有 active Secret 仅用于 discover/test，最终 revision 继续绑定同一 Secret。
- 用户提交新 API Key 且当前绑定存在时，创建新的 active Secret version。
- 当前绑定缺失但确定性 Secret code 已存在时，只有其 metadata 明确属于同一 model connection 才允许轮换并重新绑定；否则返回所有权冲突。
- 新建 Secret 与追加 connection revision 必须位于同一数据库事务中，不能留下孤立 Secret 或无 Credential 的 `ready` revision。

沿用已有 Credential 不代表回显或下发 Key。前端只能获得 configured、rotation required、masked summary、active version 和 updated time。

### 7. 前端不把API Key放入查询缓存

API Key 只保存在连接向导组件的 password input state 中。不得写入 TanStack Query data、URL、local/session storage、toast、错误对象、表单快照或持久化草稿。提交 mutation settle 后立即 reset mutation variables；关闭、导航或成功保存时立即清空字段。

模型发现结果可以保存在当前页面内存中，但 Base URL 或 Credential 变化后必须作废。公共 query 重新加载时只接收脱敏 Credential 状态。

### 8. 保留乐观并发并改善错误恢复

`expected_revision` 只在最终 `configure` 提交时使用；discover 和 test-draft 是无持久化动作，不递增 revision。409 响应必须包含当前 revision，前端收到后重新加载连接、保留非敏感表单值、清空 API Key 和测试结果，并提示管理员重新检测。

错误至少区分：

```text
deepseek_url_invalid
deepseek_credential_rejected
deepseek_model_discovery_failed
deepseek_model_list_empty
deepseek_model_unavailable
model_connection_test_failed
model_connection_test_timeout
revision_conflict
credential_ownership_conflict
```

不得把上游响应正文、Authorization header、Key、内部 URL 查询参数或 SDK stderr 原文返回给前端。

### 9. 移除旧管理API但保留领域兼容

管理 Web 和公开管理契约不再使用：

```text
PUT  /api/admin/model-connections/{code}/revision
PUT  /api/admin/model-connections/{code}/credential
POST /api/admin/model-connections/{code}/test
```

实现可以保留领域内部的追加 revision、Secret rotation 和 saved-revision test 方法供迁移、运行时或单元测试复用，但旧 HTTP 路由和前端调用必须删除，防止出现两套可写流程。

新 revision 继续使用现有 schema，因此历史 Agent Publication、已排队 Job 和旧 runtime binding 无需迁移。不可变历史记录不得被重写。

## Risks / Trade-offs

- [最终保存重复一次最小模型测试会产生少量成本和延迟] → 使用固定最小探测、单轮、短超时；换取无服务器临时状态和服务端强制验证。
- [DeepSeek模型列表与Anthropic实际可调用模型可能短暂不一致] → discover 后执行真实 SDK 测试，最终 configure 再发现并再测试。
- [用户修改输入后误以为旧测试仍有效] → 状态机在 URL、Credential、模型或 effort 变化时确定性作废下游结果。
- [并发配置在外部测试后冲突] → 提交前后两次 revision 检查；冲突不写 Secret 或 revision，并要求重新检测。
- [外部响应过大或恶意畸形] → 限制响应字节数、模型数量、字符串长度、超时和 redirect。
- [删除旧HTTP路由影响旧管理页面] → `api-server` 与 `admin-web` 必须同一版本重建和部署；不提供混跑兼容。
- [现有孤立Secret被错误绑定] → 仅允许 metadata 所有权匹配同一 model connection，其他情况失败关闭。

## Migration Plan

1. 先实现 DeepSeek URL 派生、模型发现客户端、临时 binding 测试和安全错误映射，并完成无数据库写入测试。
2. 实现 `configure` 服务和事务测试，覆盖首次创建、沿用、轮换、缺失恢复、所有权冲突和并发回滚。
3. 增加新管理 API 并完成 RBAC、审计、限流和脱敏契约测试。
4. 将 Agent Profile 页面切换为统一向导，删除 Credential Sheet 和旧三段式调用。
5. 删除旧 HTTP 路由及对应前端 API，保留必要的内部领域方法。
6. 使用同一源码状态重建 `api-server`、`admin-web`、`agent-worker` 和 `dingtalk-stream-ingress`，避免新旧契约混跑。
7. 在本地用新 Key 完成 discover、映射、test-draft 和 configure；确认当前连接从 `rotation_required` 变为 `ready`。
8. 保存、校验并发布 Agent 草稿，再按现有规则显式切换 Business Application。

回滚时必须同时回滚 `api-server` 与 `admin-web`。本变更不新增数据库表；新产生的模型连接 revision 与旧 schema 兼容，回滚不删除 revision 或 Secret。

## Open Questions

无。Provider 范围、URL 派生、模型来源、Secret 保存时机、真实测试、旧流程移除和 Agent 发布边界均已确认。
