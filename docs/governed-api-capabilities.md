# 受治理 API Capability 运维与发布

本文描述 `add-governed-api-capability-handlers` 落地后的管理 API、状态语义、
钉钉到 ONES 的完整发布链、故障处理和明确延期范围。唯一生产验收能力为
`cap__ones__work_item__search`。

## 核心对象

管理界面把配置集中在“API Capability 配置”页面，但后端对象保持分离：

| 对象 | 职责 | 发布后是否可改 |
| --- | --- | --- |
| API Connection Revision | 固定 scheme、host、port、超时与响应大小 | 否 |
| Authentication Profile Revision | 固定登录、字段提取和认证 Header 注入规则 | 否 |
| Capability Revision | 名称、业务 description、公开 Input/Output Schema、QUERY/INTERNAL | 否 |
| Handler Revision | `http-json-v1`、相对路径、固定 GraphQL Query | 否 |
| Compiled Mapping Plan | 受限 Mapping AST 的规范化编译结果 | 否 |
| Capability Release | 精确冻结以上 Revision | 配置不可改；运维状态可改 |

Capability 是 Agent 可理解、可选择的业务能力；Handler 是这个能力的外部 HTTP
实现。两者不是同一个领域对象，但管理员在同一个五区域工作台保存、Test、
Verify 和 Publish。

## 发布顺序

1. 管理员创建 ONES Connection Draft 和 Authentication Profile Draft。
2. 管理员用自己的 ONES 邮箱、一次性密码验证 Draft。密码和登录返回 Token
   仅存在于请求内，不保存、不返回。
3. 发布 Connection Revision。
4. 管理员进入“我的外部身份”，重新用自己的 ONES 账号验证，选择默认 Team，
   保存个人加密 Token。
5. 初始化或编辑 `cap__ones__work_item__search`，保存五区域草稿。
6. 用当前管理员正式个人绑定执行 Test；确认预览只含普通业务字段。
7. Verify 后以内容 hash 和幂等键 Publish Capability Release。
8. 在 Agent 草稿中选择精确 ACTIVE Release，校验并发布 Agent。
9. 在应用草稿中选择该精确 Agent Publication，再从其 Envelope 中勾选
   Capability Release 子集，配置钉钉连接器，校验、发布并激活应用。
10. 普通钉钉用户进入“我的外部身份”完成 ONES 两阶段绑定。之后该用户从命中
    活动应用的钉钉私聊或群聊发消息，运行时使用该发送人自己的 User ID、默认
    Team 和当前个人 Token。

Agent 未选择 Capability 时，应用没有可配置项；应用未选择 Release 时，模型
不会看到对应 Tool。系统没有全局启用开关，也没有 Capability `use` Grant。

## 管理 API

### Connection 与 Authentication Profile

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/admin/api-connections` | 列表、Draft 与发布历史 |
| POST | `/api/admin/api-connections` | 创建统一 Connection/Auth Draft |
| PUT | `/api/admin/api-connections/{id}/draft` | 乐观锁保存 Draft |
| POST | `/api/admin/api-connections/{id}/verify` | 当前管理员临时自验证 |
| POST | `/api/admin/api-connections/{id}/publish` | 发布精确 Revision |
| PUT | `/api/admin/api-connections/revisions/{id}/status` | 发布、停用或归档 |

### Capability

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/admin/api-capabilities` | Capability、Draft 与 Release 历史 |
| GET | `/api/admin/api-capabilities/catalog` | 发布目录 |
| POST | `/api/admin/api-capabilities` | 创建通用声明式 Capability Draft |
| POST | `/api/admin/api-capabilities/templates/ones-work-item-search` | 幂等初始化 ONES 搜索模板 |
| PUT | `/api/admin/api-capabilities/{id}/draft` | 保存五区域 Draft |
| POST | `/api/admin/api-capabilities/{id}/test` | 当前管理员绑定下执行安全预览 |
| POST | `/api/admin/api-capabilities/{id}/verify` | 生成绑定 Revision/hash 的证据 |
| POST | `/api/admin/api-capabilities/{id}/publish` | 原子幂等发布 |
| PUT | `/api/admin/api-capabilities/releases/{id}/status` | 运维状态变更 |
| POST | `/api/admin/api-capabilities/releases/{id}/copy-to-draft` | 复制历史版本为新 Draft |

### 用户个人凭据

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/me/external-identities/ones` | 只读取当前用户自己的状态 |
| POST | `/api/me/external-identities/ones/challenges` | 邮箱密码验证并取得 Team 候选 |
| POST | `/api/me/external-identities/ones/confirm` | 单次消费 Challenge 并保存默认 Team |
| DELETE | `/api/me/external-identities/ones` | 本人软解绑 |
| GET | `/api/admin/users/{id}/external-credentials/ones` | 管理员只读凭据状态 |
| PUT | `/api/admin/users/{id}/external-credentials/ones/disable` | 管理员停用凭据 |
| DELETE | `/api/admin/users/{id}/external-credentials/ones` | 管理员软解绑 |

管理员不能代用户输入 ONES 邮箱密码、读取 Token 或轮换 Token。

## Release 与故障状态

- `ACTIVE`：可供新 Agent/Application 选择并可运行。
- `DEPRECATED`：历史 Application Publication 仍可运行；新选择禁止。应填写原因，
  可指定同 Identifier 的 ACTIVE replacement。
- `DISABLED`：全部新 Tool 调用失败关闭。它是第一版最快的运行时回退手段。
- `ARCHIVED`：仅历史可见；存在活动依赖时拒绝归档，归档后不能恢复。

Connection Revision 使用 `PUBLISHED`、`DISABLED`、`ARCHIVED`。Connection
停用会使依赖它的新调用失败，不会改写历史 Release。

常见安全错误：

| error code | 含义与处理 |
| --- | --- |
| `revision_conflict` | Draft 已变化，刷新并核对最新 Revision 后重试 |
| `ones_binding_required` | 当前用户需本人绑定 ONES |
| `credential_connection_mismatch` | 用当前 Connection Revision 重新绑定 |
| `external_api_unauthorized` | ONES 返回 401，个人凭据被标记 INVALID，需重新验证 |
| `external_api_forbidden` | ONES 返回 403，凭据状态保留；检查用户/Team 业务权限 |
| `job_subject_snapshot_mismatch` | 账号或默认 Team 已变化，旧 Job 失败关闭 |
| `capability_release_unavailable` | Release 已停用或归档 |
| `mapping_execution_failed` | Mapping 输入、转换或响应结构不满足已发布计划 |
| `external_api_response_too_large` | 外部响应超过 Connection Revision 上限 |

## 数据与审计边界

控制面审计只保存 actor、对象 ID、Revision、内容 hash、动作结果、
correlation ID 和安全错误码，不保存配置正文。运行时通过以下稳定 ID 可关联：

`channel_ingress_event → agent_job → agent_job_external_subject →
agent_tool_call → agent_tool_call_http_attempt /
agent_tool_call_api_provenance → delivery_outbox`

运行时持久化 attempt 分类、HTTP 状态、耗时、大小和 hash；规范化 INTERNAL
结果沿既有 Job/Tool Call 访问控制保存。密码、Token、Cookie、认证 Header、
原始请求认证部分和原始 HTTP 响应正文不进入日志、审计、预览或运行时元数据表。

`session_policy.retention_days` 仍是 `stored_only` 配置。本变更没有增加正常 Tool
结果、会话结果或记忆的定时清理任务；后续记忆系统必须另行设计生命周期。

## 回退

回退不删除迁移数据，也不修改历史发布：

1. 将问题 Capability Release 标为 `DISABLED`，立即阻止新的 Tool 调用。
2. 激活不含该 Capability 的历史 Application Publication。
3. 必要时让应用重新选择不含该 Release 的历史 Agent Publication。
4. 保留发布历史、用户身份和加密个人凭据，修复后复制历史 Release 为新 Draft，
   重新 Test、Verify、Publish 并显式升级 Agent/Application。

旧 Agent/Application snapshot 缺少 Capability 字段时按空集合读取。

## 明确延期范围

- 只承诺固定 Origin、相对路径、生产 HTTPS、响应大小/超时限制及拒绝跨 Origin
  redirect；尚未实现通用网络区、CIDR allowlist 或 DNS 重绑定防护，不能把当前
  状态描述成完整 SSRF 防护。
- V1 不支持写操作、任意脚本、模板语言、服务端 Handler-to-Handler 管道。
- V1 不支持多 ONES 实例、同一用户多个 ONES 账号或跨 Team 查询。
- V1 不执行 Tool 结果定时清理，也不实现记忆系统。
