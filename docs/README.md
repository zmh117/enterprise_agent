# 项目文档索引

本目录按用途组织，不再把当前架构、操作手册、验收快照和历史设计放在同一层。

## 事实层级

1. **当前实现**：代码、活动迁移目录和自动化测试反映当前可运行事实。
2. **当前规范**：`openspec/specs/` 与活动 OpenSpec 变更描述目标契约；活动变更未完成的任务不能视为已实现。
3. **当前架构文档**：`architecture/` 解释已采用的系统边界。
4. **操作和指南**：`operations/` 与 `guides/` 给出可执行流程，执行前仍应核对当前分支和环境。
5. **日期化验证**：`verification/` 是某次验收快照，不自动代表现在仍通过。
6. **历史归档**：`archive/` 仅用于审计，不得作为新实现依据。

## 当前架构

- [Admin Web MVP](architecture/admin-web-mvp.md)
- [业务应用控制面](architecture/business-application-control-plane.md)
- [连续对话与多模态附件](architecture/continuous-multimodal-conversations.md)
- [多应用与共享 Agent Worker 路由](architecture/multi-application-agent-worker-and-dingtalk-bot-routing.md)
- [标准 MCP 工具服务](architecture/tool-mcp.md)
- [受治理任务文件工作区](architecture/task-file-workspaces.md)
- [统一身份、RBAC 与管理端](architecture/unified-identity-rbac-admin.md)
- [Webhook Agent Trigger](architecture/webhook-agent-triggers.md)

当前执行链是 `Channel -> Control Plane -> Worker -> Python Runtime -> MCP`。历史 `typescript-v1` Definition、Publication、Job 和审计保持只读，不再是可执行路径。只读业务工具进入 `tool-mcp -> Resource`；任务文件进入 `File MCP（File Service 内）-> 受治理版本 -> MinIO`。身份、RBAC、应用发布、资源发布、Secret、审计和 Job 历史仍由平台治理；旧 API Capability、Handler、API Connection、Resource Mapping 和 Internal API Platform 已退役。

## 指南

- [Agent 模型连接](guides/agent-profile-model-connections.md)
- [Agent 测试数据](guides/agent-test-data.md)
- [平台配置 API](guides/platform-config-api.md)
- [任务工作区 TXT/LOG/Markdown 使用说明](guides/task-file-text-formats.md)
- [Web 管理多钉钉 Runtime](guides/web-managed-multi-dingtalk-runtime.md)
- [Web Secret 与环境配置](guides/web-managed-secrets-and-env-config.md)

## 运维

- [空库 Baseline 100 与初始管理员](operations/schema-baseline-bootstrap.md)
- [Legacy 042 升级、采用与回滚](operations/schema-baseline-upgrade.md)
- [Compose PostgreSQL 18 / RabbitMQ 4 升级与恢复](operations/compose-postgres18-rabbitmq4-upgrade.md)
- [Agent 重试与失败投递](operations/agent-retry-failure-delivery.md)
- [执行策略维护](operations/execution-policy-runtime-maintenance.md)
- [平台 Master Key](operations/platform-master-key.md)
- [Master Key 紧急离线重加密](operations/emergency-master-key-reencryption.md)
- [钉钉测试数据重建](operations/dingtalk-test-data-rebuild.md)
- [Task File Workspace 切换与运行](operations/task-file-workspace-cutover.md)
- [TypeScript Agent Runtime 分阶段退役](operations/typescript-agent-runtime-retirement.md)

## 验证与参考

- [Compose PostgreSQL 18 / RabbitMQ 4 验收快照](verification/compose-postgres18-rabbitmq4-verification.md)
- [Task File Workspace 合成验收证据](verification/task-file-workspace-synthetic-acceptance.md)
- [ChatGPT 项目上下文](reference/chatgpt-context/README.md)
- [当前有效 ADR](reference/decisions/README.md)
- [文档移动清单](reference/document-inventory.md)

## 历史归档

- [已退役 API Platform 决策](archive/legacy-api-platform/README.md)
- [旧实施基线](archive/implementation-baselines/README.md)

本地执行 `make docs-link-check` 检查仓库内 Markdown 文件链接；链接失败时不得通过移动文件来“隐藏”历史引用，应修正目标或明确标记为外部/历史文本。
