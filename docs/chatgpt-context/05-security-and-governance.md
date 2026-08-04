# 安全与治理设计

## 安全目标

平台的安全目标不是“模型表现得谨慎”，而是即使模型、外部 payload 或管理员配置出现错误，仍由代码、数据模型和运行时门禁强制满足：

- 未授权主体不能创建 Job、启动 Worker、调用 Tool 或接收结果；
- Agent 只获得当前应用、当前用户和当前数据范围的最小能力集合；
- 外部 API、数据库、Redis 和 Loki 访问保持只读、有界、可审计；
- Secret 和原始外部数据不泄漏到浏览器、队列、日志、审计或模型上下文；
- 配置变化显式版本化、验证和发布，不通过浮动“最新值”改变既有运行；
- 入口、消息队列和投递的重复或故障不导致越权或重复 Agent 执行。

## 主要信任边界

```text
External User / Webhook Payload        不可信输入
        |
Channel / Webhook Authentication       入口信任建立
        |
Internal User / Service Account        平台主体
        |
Application + Role + Scope             业务授权
        |
Agent / Application Publication        冻结执行配置
        |
Tool Runtime                           模型不可信调用方
        |
Internal API Platform / API Executor   数据与外部系统边界
        |
Delivery Adapter                       外部输出边界
```

模型输出、Tool 参数、外部 API 响应和 Webhook payload 都按不可信数据处理，不能解释为系统／开发者指令。

## 身份、凭据和授权分离

必须区分五个事实：

1. **内部用户**：平台授权主体；
2. **外部身份绑定**：证明某个外部账号属于该用户；
3. **个人凭据**：调用外部 API 的加密 Token；
4. **默认 Team／外部范围**：由真实验证选择的当前业务上下文；
5. **角色、应用访问和数据范围**：平台内授权。

绑定 ONES 或钉钉不会自动授予角色、应用、Capability 或数据权限。管理员也不能把“人员详情治理模式”变成代用户输入密码或编辑外部主体字段的界面。

钉钉群聊中，每条消息按实际发送人解析内部用户和外部凭据；禁止共享群身份、机器人凭据或上一个发送者的会话权限。

## 控制面安全

- 浏览器使用高熵 HttpOnly Session cookie，数据库只保存 token hash；
- Session 同时有 idle 与 absolute expiry；
- 修改密码、停用用户和管理员撤销会使既有 Session 失效；
- 写请求要求可信 Origin 和 CSRF cookie/header 双提交；
- API 仍执行后端 RBAC，前端 capability gate 仅改善体验；
- 对无权读取的具体业务对象按不存在处理，降低枚举风险；
- Draft 更新使用 `expected_revision` 乐观锁；冲突必须刷新合并，不能强制覆盖；
- Publish 绑定已验证 revision、content hash 和幂等键；
- 验证证据在任何影响执行的字段变化后失效。

管理权限按动作拆分，例如 read、edit、test、verify、publish、activate、rotate，而不是一个“平台管理员全能”布尔值。

## 运行时多阶段授权

授权至少在以下阶段执行：

1. 入口接受和身份解析；
2. Job 创建；
3. Worker 开始执行；
4. Tool／Capability 暴露与每次调用；
5. Delivery claim 和发送前。

Job 会保存当时的授权和发布 provenance，便于审计；但用户、角色、membership、身份、凭据、资源和 Release 的实时撤销仍可阻止后续阶段。

仓库同时存在旧授权兼容事实和 `strict_application_role` 模式。基础收敛 OpenSpec 尚未完全完成，因此讨论授权时必须先核对目标部署的实际 mode，不得把 compatibility 结果当作 strict-only 已全面上线。

## Secret 管理

Secret 分三类边界：

- **Bootstrap-only**：数据库 DSN、Master Key 文件路径、部署安全开关和服务间 Token 文件；
- **DB-configurable**：非敏感 runtime config、资源 topology、模型配置；
- **Secret-managed**：模型 Key、Connector Secret、外部 Token、数据库／Redis／Loki 凭据。

主要规则：

- Master Key 本体位于仓库外的只读固定文件，不写入数据库或镜像；
- Web 输入 Secret 后只返回安全状态或受管引用，不回显明文；
- 数据库保存加密 Secret version，rotation 产生新版本；
- Model Connection、Publication、Job provenance 和审计不保存 Key 或 Secret ref；
- 每个执行 attempt 开始时解析当前 active Secret version；
- `env:` 兼容 Secret 必须通过受控迁移转为受管 Secret，不能把明文复制到文档；
- 不支持的 `vault:`／`kms:` 不得被表述为已实现。

上传 ChatGPT 时禁止包含 `.env`、Master Key、Client Secret、Token、密码、模型 API Key、数据库连接凭据、Session Webhook 或真实消息正文。

## 内置只读工具安全

### 数据库

- `SELECT`／`WITH` 单语句；
- SQLGlot AST 拒绝写语句、`SELECT INTO`、`FOR UPDATE`、批处理和 PL/SQL；
- 真实表提取，不把 CTE 名当物理表；
- 车间表前缀和 schema directory 双重约束；
- 方言正确的 `LIMIT`／`TOP`／`FETCH FIRST`／`ROWNUM`；
- 只读数据库账号、statement timeout、行数和字节上限作为纵深防御。

### Redis

- 只允许 `GET` 和有界 `SCAN`；
- key／pattern 必须在车间前缀内；
- 空 pattern 和全局 `*` 拒绝；
- Cluster 仍保持相同逻辑隔离。

### Loki

- 服务端注入车间 label；
- 请求时间范围、selector 和行数受限；
- 上游 host 和 tenant 不暴露给模型。

结构化寻址目录只返回当前用户有权访问的 environment、base、workshop 业务 code 和显示名称，不返回 IP、host、DSN 或凭据。

## 受治理 API Capability 安全

- API Connection 固定 scheme、host 和 port；Handler 只能使用相对路径；
- HTTPS 默认；明文 HTTP 必须针对单个 Draft 显式接受风险并真实验证；
- 跨 Origin redirect 拒绝，Token 不能发送到其他 Origin；
- 第一版只允许 `QUERY` 业务语义，不能仅用 HTTP Method 判断只读；
- Handler 使用固定 `http-json-v1` Executor，不支持任意代码、Shell 或模板语言；
- Mapping Plan 只能使用公开输入、固定常量和平台拥有的系统上下文；
- Password、Token、Cookie、认证 Header、User ID 和默认 Team 不属于模型可写 Input Schema；
- 当前仅允许 `CURRENT_ACTOR` Credential Subject Policy，不回退共享服务账号；
- 原始外部响应映射完成后丢弃，不进入日志、数据库、审计或模型；
- 只有 Output Schema 允许的有界规范化结果可以持久化和发送给模型。

当前固定 Origin 边界不等于完整 SSRF 防护。Network Zone、CIDR allowlist 和 DNS rebinding 防护尚未实现，任何方案评审都必须保留这个限制。

## Webhook 安全

当前公共入口：

- 每个 Trigger 独立高熵 Bearer Secret；
- public ID 可轮换；
- body 大小、JSON、schema、filter、idempotency 和 mapping 全部受限；
- 原始 Authorization、完整 endpoint、payload 正文不落库、不进队列和普通日志；
- 服务账号、Agent、Scope 和 Delivery target 来自发布快照，不来自 payload。

当前主要限制：本地／Compose HTTP 验证不等于生产公网安全；HMAC、timestamp、nonce 和完整 HTTPS 边界仍需单独设计。

## 数据分级与最小持久化

API Capability 版本声明数据分级。当前 ONES 工作项查询固定为 `INTERNAL`：

- 只允许授权应用、Job 和模型调用使用；
- Tool Call 可保存有界规范化输出；
- 原始请求／响应和认证数据不保存；
- Audit 保存对象 ID、版本、主体、Team、安全状态、耗时、数量和 hash；
- `session_policy.retention_days` 当前主要是已保存配置，没有定时清理执行器；
- 后续记忆系统必须继承用户、应用、Capability 和数据分级来源边界。

## 审计与脱敏

安全审计建议以稳定 ID 和安全摘要为主：

```text
channel/webhook event
  -> application publication
  -> job + external subject / execution scope
  -> tool call + HTTP attempt / provenance
  -> artifact
  -> delivery outbox / attempt / chunk
```

禁止写入审计或普通日志：

- Password、Token、Cookie、CSRF、Client Secret、模型 API Key；
- Secret 密文和可解析引用；
- 完整外部身份标识、完整 Webhook URL、Session Webhook；
- 原始 DingTalk／Webhook payload 和外部 HTTP 响应正文；
- 未脱敏的内部业务日志或个人信息。

## Fail-closed 场景

以下任何条件不满足都不能自动回退到默认 Agent、其他用户、其他 Team、旧 Secret 或另一个应用：

- 无活动 Business Application route；
- 外部身份未绑定、冲突、停用或企业未验证；
- 用户、角色、membership 或应用访问无效；
- Agent／Application Publication hash 不一致；
- Tool／Capability／Connection／Resource 被禁用；
- 个人凭据无效、连接版本不匹配或默认 Team 漂移；
- Mapping、Schema、响应大小或字段转换失败；
- runtime generation、Master Key、服务 Token 或 schema head 不可用。

## 尚未完成的安全能力

- 完整网络出口治理和通用 SSRF 防护；
- Vault／KMS Provider；
- 生产 Webhook HTTPS/HMAC/replay protection；
- Agent Worker lease、fencing、cancel 和 RUNNING 崩溃恢复的完整模型；
- Tool 结果／会话／记忆的自动生命周期和定时清理；
- 附件恶意软件扫描、OCR、视觉模型和隔离式旧 Office/PDF 处理；
- 多环境、生产发布审批、跨区域灾备。

## 关键源文件与 ADR

- `CONTEXT.md`
- `docs/adr/0002-use-governed-declarative-capability-handlers.md`
- `docs/adr/0005-resolve-external-api-credentials-from-current-actor.md`
- `docs/adr/0015-capability-owns-public-schema-handler-implements-it.md`
- `docs/adr/0021-persist-only-bounded-normalized-capability-output.md`
- `docs/adr/0038-pin-agent-publications-and-revalidate-application-capability-subsets.md`
- `docs/adr/0042-freeze-job-subject-without-bypassing-live-revocation.md`
- `docs/adr/0048-allow-explicit-plain-http-api-connections.md`
