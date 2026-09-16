# execution / task-file / document baseline rebuild

已仅修改这三份 canonical spec；未移动 change、未改代码、未读取旧 archive 或真实凭据/业务正文，未访问外部系统。

## 当前实现核对与重建

- execution-delivery：将旧 debug/runtime/outbox/delivery/审计多次拼接收敛为任务事实、可靠调度、Runtime、工具/上下文、审计、投递、外部确认七组。原 2441 行现约 1312 行；保留最小 MQ、事务 Outbox、幂等 claim、当前权限复核、terminal 提交后 ack、执行与投递分离、有限 replay 等合同。
- Runtime 当前1.5，支持1.4；旧1.0–1.3无执行/投影路径。Manifest当前v5。删除旧仅1.3/仅1.4、隐式全局model config/env fallback、TypeScript迁移阶段操作和重复固定只读总括。`runtime_protocol.py` / `runtime_http_client.py` / `model_binding.py` / `mcp_config.py`已核对。
- 运行预算 `ExecutionPolicyValues` 当前 max_turns 1–100、timeout10–3600、max_tool_calls0–500；默认30见config。权限回调每次consume，耗尽interrupt=True，Runtime本地timeout不重试。没有声称业务应用提交0可用：root已发现其保存逻辑0->30，执行规范只定义合法冻结有效0的语义。
- 工具effective registry、首次模型前File MCP分页tools/list校验、四层不可变tool_contract_observed、Prompt v7共享事实、DRIFT优先级、规范协议错误差异均保留。吸收paginate-ones的安全错误时间线；计数returned不得用total替代。
- 完整审计：RunAuditRecorder直接_jsonable保存实际SDK消息/API bodies、没有应用层正文脱敏或thinking过滤。纠正旧“完整审计也不保存SDK thinking”的不实绝对声明：普通安全事件/主账不存私有推理，完整专用链保存实际暴露响应，不推断/伪造隐藏内容，认证对象不主动复制。40KiB*1600传输块、1.5流边界、每字段64Ki字符延迟分页、Job scope前置以及无正文初始详情已对账。
- governed-external-action-confirmation 的6个旧Requirement已吸收并纠正revise：当前回调返回固定“回原会话修改”提示，保持原状态，无Provider副作用；支持的提案替代另创建完整意图/链，旧intent SUPERSEDED，新intent重确认。
- 外部操作新发现差异：独立worker串行run_once + 单intent数据库条件claim已实现；没有全局并发槽位/配置，Compose health只判断heartbeat文件存在。原“必须有独立全局并发上限”重写为实际worker/claim能力，并在实现边界明确未实现之处。恢复固定Provider只读对账失败进入FAILED_UNCERTAIN，不自动重放。
- task-file-workspace：填补TBD Purpose，吸收执行域受控桥/输出选择、本轮准入、日志扫描/输入容错、ONES只读结果文件以及builtin域File MCP授权、失败错误、目录/working-set细节。清理“第一阶段拒绝Office”“+08机器时间”“所有暂存附件都自动认领”“单一时段候选自动物化”等与代码矛盾条款。
- file_context.py 的 FileAdmissionPlan已落地：输出意图/依赖/Gate/workspace/manifest统一决策；TIME_WINDOW最多20元数据，output-only零依赖，来源等待从file_turn_dependencies恢复。依赖优先级与指示语按代码限定，WAITING_INPUT不等待Docling。
- Manifest v5、catalog不可变revision、20/50分页、40输入working set、64总文件/40输入/16work-output/8内部/224MiB、原件/Markdown/JSON区分、流式整批预留、commit幂等与冲突、保留/清理均保留。补回真实CLI权限回调绝对路径仅还原本次sandbox安全相对路径的合同。
- 群工作区新发现差异：TaskWorkspaceService.get_active_workspace(session_id)按Session找活动工作区；GROUP_CONVERSATION owner只是授权边界，不保证不同群成员/不同Session共享实例。已与channel agent对齐并改写旧共享承诺。
- document-file-processing：Profile唯一NONE/docling-layout-ocr-v2，三种表示完整发布；平台模型digest完整映射入hash，当前平台选择校验；WPS ../NULL只处理安全零尺寸占位且只改临时副本；multi-provenance charspan确定展开、confidence可null、最终block上限、双数据库槽位占用/恢复/隔离全部按代码加入。保留原件不变、OCR非视觉语义、raw embedded media after EXIF、Office显示变换不应用、PARTIAL/NO_TEXT、硬软上限和资产清理。

## 关键代码/测试定义

- backend/app/modules/job/application/{create_agent_job_service,file_context,job_retry_service}.py
- backend/app/modules/job/domain/{execution_policy,job_status}.py
- backend/app/modules/agent/infrastructure/{runtime_protocol,runtime_http_client}.py
- backend/app/python_runtime/{executor,claude_client,mcp_config,tool_contract,tool_policy,model_binding,run_audit,invocations,job_sandbox,file_mcp_bridge,log_evidence_scanner,ones_result_bridge}.py
- backend/app/shared/{tool_contract,agent_run_audit_codec}.py
- backend/app/modules/job/infrastructure/repositories.py; backend/app/modules/admin/api/controller.py
- backend/app/modules/file_workspace/{workspace_service,authorization,manifest_service,quota,text_format_policy,streaming_service,repository}.py
- backend/app/modules/document_processing/{profile,model_artifact,source_validation,provider,layout_ocr,worker_service,service,repository}.py
- backend/app/modules/external_action/{service,repository,domain,card}.py
- services/external_action_worker/runtime.py; services/dingtalk_mcp_server/worker.py; docker-compose.yml
- backend/tests/test_agent_job_file_admission.py、test_document_layout_ocr.py、test_file_processing_worker.py等测试定义（未执行业务测试）。

## 验证

- `openspec validate execution-delivery --type spec --strict` 通过。
- `openspec validate task-file-workspace --type spec --strict` 通过。
- `openspec validate document-file-processing --type spec --strict` 通过。
- `git diff --check` 通过。
- 三份均无重复Requirement标题、无Reconciled/Integrated历史拼接注释。领域内导航使用加粗文本，避免此仓库OpenSpec解析器遇到中途`##`把Requirement视为区段外。

## 验收边界与欠账

没有执行全套测试、建镜像、部署、迁移、真实模型/MCP/Docling/钉钉/对象存储/生产数据库调用。原29 changes/22未勾选验收由root保留；本次关闭不构成验收通过。另发现的group session/workspace共享限制、external worker全局并发与heartbeat限制是代码与旧文档差异，不擅自补代码或将其记为通过。业务完整清单Prompt规则仍为模型约束，不是程序完整性保证。

## 交叉事实复核修正：Job scope 与 ONES 主体

- `AgentJob`、repository 的 Job 列集合和 migration 100/101 没有 Job execution_scope 表/列；创建服务只保存入口 routing_context、internal_user_id、source external_identity_id、Publication 与授权摘要。`_execution_scope_hash` 是 Session 会话隔离事实。`JobMcpToolSnapshotService._persist` 明确 `del routing_context`，冻结工具 schema/effect/confirmation 合同及 authorization hash，不冻结调用目标/placement。已修正 execution 前两条及重试/Runtime 场景，不再误称 Job 固定业务 Execution Scope。
- 调试 API 确实仍接受 `execution_scope_id`；`DebugJobAccessService` 只从当前授权候选选择，写 routing_context 与 route_decision 的调试来源，参与幂等/Session 隔离。已保留此接口事实并说明它不创建 Job 目标快照或替代 Tool Call 授权。
- 删除错误旧条款“External Execution Subject Snapshot 不随绑定变化漂移”：Job 无 ONES User/default Team 快照。`services/ones_mcp_server/auth/principal.py` 每次按 Job 内部请求人解析唯一当前 enabled ONES 身份、当前有效 default Team 与 ACTIVE Credential，先复核 RUNNING Job/Principal/工具快照/当前应用授权。入口 external_identity_id 来源引用不可与 ONES 执行身份混淆。
- 写操作另有不可变 Intent：`services/external_action_worker/ones_adapter.py:_reauthorize` 以 Intent 的 execution_external_identity_id 精确取仍启用身份，并检查 Intent Team 仍在当前 team_uuids；不要求它仍为 default Team，且不把原意图改到新默认 Team。创建操作还有 identity_revision 等对应前置条件，已保留其拒绝边界。
- 核对测试定义 `test_mcp_tool_runtime.py::test_job_snapshot_does_not_freeze_routing_target_or_resolve_a_resource`、`test_ones_mcp_runtime.py` 的 current identity/default Team/credential 检查、`test_ones_task_update.py::test_ones_worker_reauthorizes_exact_identity_and_frozen_team`；只阅读定义，未额外运行涉及业务的测试。已通知 identity/channel agent 与 root 统一边界。
- 此轮修正后再次执行 `openspec validate execution-delivery --type spec --strict` 与 `git diff --check`，均通过。
