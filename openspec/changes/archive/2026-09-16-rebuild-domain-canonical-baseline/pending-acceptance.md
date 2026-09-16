# 历史未完成验收清单

本清单按归档前tasks原样列出22项未勾选任务；归档关闭不代表通过。历史条目中的旧协议、旧工具和旧阶段可能已被现代码替代，后续应按canonical与当前实现重新设计验收，不能直接重跑历史维护命令。

本次未访问真实Provider、未重新发布应用、未发送消息或重启服务。

## add-agent-job-context-audit

[原始任务](../2026-09-16-add-agent-job-context-audit/tasks.md)

- [ ] 5.3 重建受影响服务并以新 Job 验证运行成功、`agent_run_audit` 持久化及调优摘要/折叠正文展示

## add-governed-dingtalk-user-message

[原始任务](../2026-09-16-add-governed-dingtalk-user-message/tasks.md)

- [ ] 1.2 使用全新钉钉 Job 验证联系人搜索真实命中、分页和两个同名 userId，再完成 Phase 2 的剩余验收、严格校验、spec 同步与归档。
- [ ] 1.3 重新读取归档后 canonical 的相关 identity、channel、tool、execution 和 operations Requirement，对账并严格校验本 change 的 delta。
- [ ] 6.3 创建新 Agent Publication、Application Publication 和角色 grant，并通过全新 Job 验证新 Tool 可见、未授权及旧 Job 不可见。
- [ ] 6.4 在真实钉钉环境验证两个同名人员的搜索与人工消歧、单人发送同意/取消、多人整批发送同意/取消和重复点击。
- [ ] 6.5 核对每条真实链的 Job、Tool Call、Intent、卡片、唯一 Provider attempt 与外部收件结果，保存有界脱敏证据并确认无凭据、正文或完整用户目录泄露。

## add-governed-ones-bug-create

[原始任务](../2026-09-16-add-governed-ones-bug-create/tasks.md)

- [ ] 8.5 使用新测试角色、Agent/Application Publication 和新 Job 完成 Mock 全链：草稿补充、完整提案、私聊卡片、确认/拒绝/过期、修订替代、创建、回查、409/超时、未知结果及无 Secret 审计。
- [ ] 8.6 在取得真实 ONES 权限/布局/UUID 回查合同后完成真实 Provider 创建与异常核验；当前无真实服务时保持未完成，不以 Mock 替代。
- [ ] 8.7 使用真实钉钉私聊与群聊保存从 Job、Tool Call、Intent、卡片点击、Provider attempt 到结果卡片的完整审计证据；当前无真实服务时保持未完成。

## add-governed-ones-task-update

[原始任务](../2026-09-16-add-governed-ones-task-update/tasks.md)

- [ ] 7.4 以新 Agent/Application Publication 和新 Job 完成真实 ONES 验收：钉钉私聊/群聊来源私发同模板卡片、Web 拒绝、单/多字段修改、状态/非缺陷拒绝、清空、超长差异、拒绝卡片、任意更新戳冲突、确认后解绑身份、Provider 失败以及成功回读。
- [ ] 7.5 保存不含 Secret 的 Action Intent、MCP call、Agent Tool Call、Job、卡片点击、Provider attempt 和结果卡片审计证据，并明确区分自动测试通过与真实端到端验收通过。

## enable-oracle-resource-live-verification

[原始任务](../2026-09-16-enable-oracle-resource-live-verification/tasks.md)

- [ ] 2.3 另一环境部署后，通过 Web 完成真实 Oracle 11.2.0.4 技术测试并核对发布资格（需用户环境，不以 Mock 代替）。

## expand-governed-dingtalk-mcp-phase-2

[原始任务](../2026-09-16-expand-governed-dingtalk-mcp-phase-2/tasks.md)

- [ ] 8.3 分别验收待办、日历、AI 表格记录、机器人消息和工作通知 mutation 的同意链，关联 Job、Tool Call、Intent、卡片、唯一 Provider attempt 与真实外部结果
- [ ] 8.4 分别验收上述 mutation 的拒绝链，证明 Intent 为 REJECTED、Provider 写入 attempt 为零且卡片终态不可再次执行
- [ ] 8.5 保存不含 Secret、Token 或无界业务正文的发布/回滚证据，确认排除的删除、撤回、DING、任意目标和结构修改 Tool 不可见

## expose-job-tool-contract-evidence

[原始任务](../2026-09-16-expose-job-tool-contract-evidence/tasks.md)

- [ ] 6.4 在维护窗口预检并排空或显式取消所有非终态protocol 1.3 Job、outbox、delivery和队列事实；任一安全计数非零时停止切换，不运行双协议消费者。
- [ ] 6.5 使用同一发布清单整体重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，创建新的protocol 1.4 Agent/Application Publication，并验证各组件revision/build ID/platform及可得digest。
- [ ] 6.6 运行无附件文字Job、File MCP读取、`select_sandbox_output → file_create_commit_intent → file_deliver_version`、缺失提交工具失败关闭和断线恢复的新鲜Compose E2E，核对运行记录四层事实与实际ToolUse/ToolResult后再恢复入口。

## paginate-ones-graphql-list-tools

[原始任务](../2026-09-16-paginate-ones-graphql-list-tools/tasks.md)

- [ ] 5.3 重新发布 Agent/Application 后，对真实 ONES 的 provider-cursor 与 snapshot-offset 代表 Tool 完成只读首/续/终页验收；无授权或无足量数据时明确保留待验收
- [ ] 6.6 对明确选定的 Agent/Application 重新发布，以新 Job 完成真实 ONES 查询、文件读取和失败时间线验收；不能以 Mock 或容器健康替代

## paginate-ones-work-item-search

[原始任务](../2026-09-16-paginate-ones-work-item-search/tasks.md)

- [ ] 4.2 重新发布 Agent 与业务应用后，用超过 50 条的真实只读结果完成续页与终页验收；若无可用数据则明确保留为真实环境待验收

## pin-docling-model-digests-by-platform

[原始任务](../2026-09-16-pin-docling-model-digests-by-platform/tasks.md)

- [ ] 3.3 在可用的AMD64与ARM64镜像环境验证固定index对应的模型目录digest，并明确区分本机实证与待发布验收
