# Identity / Channel 基线重建报告

日期：2026-09-16。范围仅为 `openspec/specs/identity-access/spec.md` 和 `openspec/specs/channel-conversation/spec.md`。未修改代码、changes 或 archive，未读取 archive 正文、实际 Secret/env 原值或真实业务消息。

## 结果

| 主规格 | 原 Requirement / Scenario / 行 | 新 Requirement / Scenario / 行 |
|---|---:|---:|
| identity-access | 183 / 428 / 2522 | 30 / 84 / 445 |
| channel-conversation | 101 / 264 / 1447 | 29 / 77 / 415 |

全部历史 `Reconciled` / `Integrated from` 拼接注释已移除。按身份主体、认证、管理能力、RBAC、企业身份、候选、ONES 自助 Credential、Principal 和执行前身份复核组织 identity；按 Connector、Runtime/ACK、规范化与路由、Session、附件交接、原会话/文件/主动消息、卡片、Webhook 组织 channel。跨领域通过 canonical 名称引用而非复制全文。

## 已核对的 active delta

- `allow-rebinding-unbound-ones-identity/specs/identity-access/spec.md`
- `add-governed-ones-task-update/specs/identity-access/spec.md`
- `add-governed-dingtalk-user-message/specs/identity-access/spec.md`
- `add-governed-dingtalk-user-message/specs/channel-conversation/spec.md`
- `expand-governed-dingtalk-mcp-phase-2/specs/identity-access/spec.md`
- `expand-governed-dingtalk-mcp-phase-2/specs/channel-conversation/spec.md`

还从原 canonical 快照吸收 builtin 的管理/RBAC/业务范围/Job-context 与 File/Service Principal 条款、governed-api 前部的 ONES Challenge/Credential/Team/自助治理条款。File 参数与实时工作区授权由 task-file-workspace 承接；钉钉测试数据重建保护由 root 的 platform-operations 承接；通用 Action Intent 状态机和审计链由 execution-delivery 承接。

## 纠正和移除原因

1. 移除旧原型、仅用户MVP页面、角色/会话未开放、仅默认Agent可编辑等阶段性限制。当前角色管理、真实用户/身份、自助Session与多Agent已有实现；不再把旧阶段描述作为当前禁令。
2. 原“至少保留最后一名平台管理员”与旧 builtin“两名”冲突。按 `identity/infrastructure/repository.py::require_verified_human_platform_admins(minimum=2)`、`authorization_center/application/service.py::update_members` 和 `identity/application/admin_service.py` 写为：减少已登录验证人类管理员的事务不得降到两人以下；首次 bootstrap 可以创建第一名，并非系统初始化先验已有两人。
3. 删除 `permission_policy` / `platform_access_grant` 参与 runtime 或允许 fallback 的旧条款。现 `identity/application/authorization.py` 与统一角色控制面只使用严格 RBAC；稳定Tool、应用、范围和Provider交集分别保留。
4. ONES解绑历史只结束绑定周期，不再阻止另一经本人验证的用户创建新当前记录；disabled仍占当前主体。依据 migration126、migration130与 `test_ones_identity_binding.py` 的已解绑跨用户新绑定、disabled占用、唯一竞态测试。钉钉历史原人员归属继续跨状态不可转移。
5. 个人Credential与身份分开；两阶段加密Challenge、Team重新验证、原子确认、刷新与需重新认证、本人/管理员投影保留。删除“不持久化登录材料”的旧误导，改为不暴露、用途绑定加密持久化，不把Credential当作权限。
6. Principal按Server audience封闭签发；业务/文件/内部服务使用独立验证合同。同签名根下 Service Principal 当前包含 `file-worker`、`file-processing-worker`、`delivery-worker` 三种角色，不只旧两角色。Token TTL<=300；不以旧ONES专用签发方法代表全部MCP。
7. **active delta 已落后当前钉钉合同**：`shared/dingtalk_tool_contracts.py` 将 `dingtalk_send_robot_message` 列在 `DINGTALK_EXCLUDED_TOOL_IDENTIFIERS`；当前工具为 `dingtalk_send_message_to_group_by_robot`、target_policy=`current_source_group`，私聊拒绝。canonical已纠正为当前群工具、明确user_ids批量单聊、本人工作通知三种独立语义，并保留普通Delivery完全独立。external agent 已核对一致。
8. Connector用途确认卡模板现有 `shared/dingtalk_card_templates.py`、managed service/controller、migration128及前端表单实现；不沿用“未实现”的旧状态。唯一用途 external_action_confirmation，缺模板阻止新mutation，不把它表示为Stream断线。
9. 应用Channel路由当前 `_resolve_business_application` 固定 `environment='local'`；原任意部署环境自动选择不能作为已实现事实。已区分部署路由与业务routing环境。
10. **群会话事实纠正**：`create_agent_job_service.py::_session_key` v2 群聊仅清空requester_scope，仍包含external_identity_id；execute与stage_attachments均原样传入。不能承诺不同真实群成员共享同一Agent Session。task-file-workspace agent已同步修正：group owner约束不自动合并不同session_id工作区。
11. ConversationContext默认是 `BoundedConversationSummarizer` 的确定性有界摘录；没有额外模型摘要能力。保留版本/sequence并发控制、预算和失败降级，删除把完整附件文本普遍注入上下文的旧承诺。
12. 纯附件暂存和后续文字按AdmissionPlan硬证据衔接，删除“任意后续文字认领全部暂存附件”旧场景；WAITING_INPUT只等冻结来源依赖，Docling未就绪按固定说明终结。详细TIME_WINDOW/Manifest/格式/OCR规则移交文件canonical，避免冲突。
13. Webhook receive代码没有完成全部业务角色授权：202仅是认证/结构/映射/限流后Inbox受理；dispatcher再检查状态与Channel/应用授权。已删除“202前全部业务授权通过”的不实承诺。
14. Webhook cooldown当前把时间窗编号加入dedup_key，跨窗口可以创建新诊断Event/Job，不能写所有相同groupKey永久只创建一个。已保留配置窗口边界。
15. 当前 `ConnectorRegistry.assert_host_allowed` 对配置非空host_allowlist做拒绝，空列表不构成统一默认拒绝；Stream session webhook专用Adapter也没有同一通用allowlist。canonical明确适用策略及证据限制，不再暗示全部公网出站防护已完成。

## 主要代码和测试证据

- `backend/app/modules/identity/application/auth_service.py`
- `backend/app/modules/identity/application/admin_service.py`
- `backend/app/modules/identity/api/dependencies.py`
- `backend/app/modules/identity/infrastructure/repository.py`
- `backend/app/modules/authorization_center/application/service.py`
- `backend/tests/test_unified_identity_rbac.py`
- `backend/tests/test_management_surface_authorization.py`
- `backend/tests/test_role_authorization_control_center.py`
- `backend/app/modules/identity/application/ones_identity_binding.py`
- `backend/app/modules/identity/infrastructure/ones_identity_verifier.py`
- `backend/app/modules/identity/infrastructure/ones_identity_challenges.py`
- `backend/app/modules/identity/infrastructure/external_identity_credentials.py`
- `backend/migrations/126_release_unbound_ones_identity.sql`
- `backend/migrations/130_restore_dingtalk_identity_indexes.sql`
- `backend/tests/test_ones_identity_binding.py`
- `backend/tests/test_external_identity_credentials.py`
- `backend/app/modules/identity/application/principal_jwt.py`
- `backend/app/modules/identity/application/service_principal.py`
- `backend/app/shared/mcp_server_policy.py`
- `backend/tests/test_principal_jwt.py`
- `backend/tests/test_business_mcp_principal_policy.py`
- `backend/tests/test_service_principal_identity.py`
- `backend/app/modules/channel/infrastructure/connector_registry.py`
- `backend/app/modules/channel/application/channel_ingress_service.py`
- `backend/app/modules/managed_channel/application/service.py`
- `backend/app/modules/dingding/application/dingtalk_stream_service.py`
- `backend/app/modules/job/application/create_agent_job_service.py`
- `backend/app/modules/agent/application/conversation_context.py`
- `dingtalk-runtime/src/sdk-client.ts`
- `dingtalk-runtime/src/runtime-manager.ts`
- `dingtalk-runtime/src/control-api.ts`
- `dingtalk-runtime/test/runtime-manager.test.ts`
- `dingtalk-runtime/test/control-api.test.ts`
- `backend/tests/test_managed_multi_dingtalk_runtime.py`
- `backend/tests/test_dingtalk_stream_ingress.py`
- `backend/tests/test_dingtalk_identity_observations.py`
- `backend/tests/test_dingtalk_identity_discovery.py`
- `backend/app/shared/dingtalk_tool_contracts.py`
- `backend/app/shared/dingtalk_card_templates.py`
- `backend/tests/test_dingtalk_mcp_runtime.py`
- `backend/app/modules/webhook/application/ingress_service.py`
- `backend/app/modules/webhook/application/dispatch_service.py`
- `backend/app/modules/webhook/application/trigger_service.py`
- `backend/tests/test_webhook_api.py`
- `backend/tests/test_webhook_ingress_dispatch.py`
- `backend/tests/test_webhook_mapping_security.py`
- `backend/tests/test_webhook_outbox_recovery.py`

## 本次验证

- `openspec validate identity-access --strict`：通过。
- `openspec validate channel-conversation --strict`：通过。
- `git diff --check -- openspec/specs/identity-access/spec.md openspec/specs/channel-conversation/spec.md`：通过。
- 未执行代码测试、实际迁移、真实Provider、登录、Webhook、Stream或Delivery；测试文件仅静态覆盖，不声称本次通过。29 active归档及22未完成任务保留由root处理。
