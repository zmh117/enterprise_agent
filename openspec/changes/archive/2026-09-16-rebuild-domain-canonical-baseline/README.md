# 2026-09-16 按代码重建领域主规格

用户明确批准保留10个领域、按代码事实修改旧文档、关闭此前全部active change、原样保留archive和未完成验收。本记录是历史审计材料，不是canonical规范，也不是默认Codex上下文。

## 结果

- 12份旧主规格收敛为10个领域；ONES与钉钉业务合同归governed-api-capability，通用Action Intent归execution-delivery，身份与文件合同各归所属领域。
- 29个历史active目录原样移动；22项未完成任务没有补勾。
- 既有73个archive目录及全部文件保留；本次另增29个历史关闭目录与本记录目录。
- 默认读取入口为仓库AGENTS.md、openspec/config.yaml和主规格导航。当前代码、主规格与真实环境证据仍分别判断。
- 本次仅修改文档与归档位置，没有修改产品实现、发布应用、部署服务或调用真实Provider。

## 来源与完整性

原12份主规格冻结在original-specs/；original-specs-manifest.json记录原相对路径与SHA-256。preservation-manifest.json冻结既有archive与29个来源目录的文件摘要，change-closure.json记录关闭路径、原任务计数与领域映射。文件摘要仅用于完整性核验，不包含原业务消息或凭据正文。

领域代码核对报告见reconciliation/。旧delta与当前代码冲突时以用户本次“按代码事实”授权修正，未把过时提案机械提升为现能力。原任务文本与旧主规格仍可按本记录追溯。

## 未完成事项

[22项原始未完成验收](pending-acceptance.md)保留原文。新发现的实现边界包括：应用max_tool_calls输入0归一化30、跨成员群Session/Workspace不保证共享、外部worker无全局并发槽位与严格心跳时效检查、Provider真实创建预检和权限仍需现场证据；本次没有顺手修改这些代码行为。

## 关闭清单

| 历史change | 已勾选 / 未勾选 | 当前领域 |
| --- | ---: | --- |
| [add-agent-job-context-audit](../2026-09-16-add-agent-job-context-audit/tasks.md) | 24 / 1 | execution-delivery |
| [add-authorized-tool-resource-discovery-pagination](../2026-09-16-add-authorized-tool-resource-discovery-pagination/tasks.md) | 16 / 0 | builtin-tool-resource |
| [add-bounded-log-evidence-scanner](../2026-09-16-add-bounded-log-evidence-scanner/tasks.md) | 22 / 0 | execution-delivery, task-file-workspace |
| [add-governed-dingtalk-user-message](../2026-09-16-add-governed-dingtalk-user-message/tasks.md) | 21 / 5 | channel-conversation, governed-api-capability, identity-access, platform-operations |
| [add-governed-ones-bug-create](../2026-09-16-add-governed-ones-bug-create/tasks.md) | 44 / 3 | governed-api-capability |
| [add-governed-ones-task-update](../2026-09-16-add-governed-ones-task-update/tasks.md) | 34 / 2 | governed-api-capability, identity-access |
| [add-ones-mcp-query-interfaces](../2026-09-16-add-ones-mcp-query-interfaces/tasks.md) | 17 / 0 | governed-api-capability |
| [allow-rebinding-unbound-ones-identity](../2026-09-16-allow-rebinding-unbound-ones-identity/tasks.md) | 10 / 0 | identity-access |
| [allow-resource-scoped-loki-labels](../2026-09-16-allow-resource-scoped-loki-labels/tasks.md) | 8 / 0 | builtin-tool-resource |
| [configure-tool-resource-roles](../2026-09-16-configure-tool-resource-roles/tasks.md) | 7 / 0 | builtin-tool-resource, platform-operations |
| [deepen-agent-job-file-admission](../2026-09-16-deepen-agent-job-file-admission/tasks.md) | 17 / 0 | task-file-workspace |
| [enable-oracle-resource-live-verification](../2026-09-16-enable-oracle-resource-live-verification/tasks.md) | 6 / 1 | builtin-tool-resource |
| [enforce-runtime-execution-budgets](../2026-09-16-enforce-runtime-execution-budgets/tasks.md) | 19 / 0 | business-application, execution-delivery |
| [expand-governed-dingtalk-mcp-phase-2](../2026-09-16-expand-governed-dingtalk-mcp-phase-2/tasks.md) | 44 / 3 | channel-conversation, governed-api-capability, identity-access, platform-operations |
| [expose-job-tool-contract-evidence](../2026-09-16-expose-job-tool-contract-evidence/tasks.md) | 25 / 3 | execution-delivery, platform-operations |
| [extend-ones-mcp-query-conditions](../2026-09-16-extend-ones-mcp-query-conditions/tasks.md) | 18 / 0 | agent-model, governed-api-capability |
| [fix-loki-resource-scope-form](../2026-09-16-fix-loki-resource-scope-form/tasks.md) | 4 / 0 | builtin-tool-resource |
| [harden-log-evidence-tool-inputs](../2026-09-16-harden-log-evidence-tool-inputs/tasks.md) | 4 / 0 | execution-delivery, task-file-workspace |
| [harden-oracle-client-windows-build](../2026-09-16-harden-oracle-client-windows-build/tasks.md) | 9 / 0 | builtin-tool-resource |
| [import-ones-knowledge-text-foundation](../2026-09-16-import-ones-knowledge-text-foundation/tasks.md) | 9 / 0 | platform-operations |
| [normalize-wps-null-image-placeholders](../2026-09-16-normalize-wps-null-image-placeholders/tasks.md) | 5 / 0 | document-file-processing |
| [paginate-ones-graphql-list-tools](../2026-09-16-paginate-ones-graphql-list-tools/tasks.md) | 38 / 2 | execution-delivery, governed-api-capability, task-file-workspace |
| [paginate-ones-work-item-search](../2026-09-16-paginate-ones-work-item-search/tasks.md) | 10 / 1 | governed-api-capability |
| [pin-docling-model-digests-by-platform](../2026-09-16-pin-docling-model-digests-by-platform/tasks.md) | 8 / 1 | document-file-processing, platform-operations |
| [preserve-complete-detail-replies](../2026-09-16-preserve-complete-detail-replies/tasks.md) | 3 / 0 | execution-delivery |
| [recover-agent-publication-after-runtime-upgrade](../2026-09-16-recover-agent-publication-after-runtime-upgrade/tasks.md) | 14 / 0 | agent-model |
| [repair-backend-baseline-regressions](../2026-09-16-repair-backend-baseline-regressions/tasks.md) | 11 / 0 | platform-operations |
| [scale-docling-processing-concurrency-two](../2026-09-16-scale-docling-processing-concurrency-two/tasks.md) | 20 / 0 | business-application, document-file-processing, platform-operations |
| [support-docling-multi-provenance-ocr](../2026-09-16-support-docling-multi-provenance-ocr/tasks.md) | 16 / 0 | document-file-processing |

## 本次验证

- `openspec list --json`：active changes为空。
- `openspec validate --specs --strict --no-interactive`：10/10通过。
- `make docs-link-check`、`git diff --check`：通过。
- 摘要核验：既有archive的893个文件、29个移动目录的193个文件以及12份原主规格快照均与重建前一致；22项未完成任务文本一致。
- 隔离内存SQLite：当前Migrator执行33项目录，head132，SchemaHeadValidator通过；这不是现网PostgreSQL升级证据。
- 未运行产品完整测试套件、构建部署或真实Provider/E2E。OpenSpec格式通过不能替代真实环境验收。
