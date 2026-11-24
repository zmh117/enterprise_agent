# 项目文档索引

本目录按用途组织，不再把当前架构、操作手册、验收快照和历史设计放在同一层。

## 事实层级

1. **当前实现**：代码、活动迁移目录和自动化测试反映当前可运行事实。
2. **Canonical 规范**：[10 个领域主规格](../openspec/specs/README.md) 是当前已接受基线。后续 change 只表达相对 canonical 的增量。
3. **当前架构文档**：`architecture/` 解释已采用的系统边界。
4. **操作和指南**：`operations/`、`runbooks/` 与 `guides/` 给出可执行流程，执行前仍应核对当前分支和环境。
5. **验收欠账**：[真实环境验收欠账](acceptance-backlog.md) 记录尚缺目标环境或真实 Provider 证据的项；关闭 change 或文档更新不得补勾。
6. **历史记录**：明确标记为“已完成迁移/退役记录”的 operation，以及 Git 历史中的旧文档，仅用于审计，不得按当前操作手册执行。

## 当前架构

- [Admin Web 当前实现](architecture/admin-web-mvp.md)
- [业务应用控制面](architecture/business-application-control-plane.md)
- [连续对话与多模态附件](architecture/continuous-multimodal-conversations.md)
- [多应用与共享 Agent Worker 路由](architecture/multi-application-agent-worker-and-dingtalk-bot-routing.md)
- [标准 MCP 工具服务](architecture/tool-mcp.md)
- [统一身份 ONES MCP](architecture/identity-aware-ones-mcp.md)
- [受治理任务文件工作区](architecture/task-file-workspaces.md)
- [统一身份、RBAC 与管理端](architecture/unified-identity-rbac-admin.md)
- [Webhook Agent Trigger](architecture/webhook-agent-triggers.md)

当前执行链是 `Channel -> Control Plane -> Worker -> Python Runtime -> MCP`，数据库只允许 `python-v1` Runtime。DB/Redis/Loki进入`tool-mcp -> Published Resource Revision`；ONES和钉钉分别通过业务MCP复核当前身份；可选 Knowledge MCP 按当前 KB 授权与个人 ONES 可读性返回工作项引用；mutation进入`Action Intent -> 用户确认 -> external-action-worker`；任务文件进入File Service的版本、表示与对象存储边界。旧动态API Capability、Handler、API Connection、Resource Mapping和Internal API Platform已退役。

## 指南

- [Agent 模型连接](guides/agent-profile-model-connections.md)
- [Agent 测试数据](guides/agent-test-data.md)
- [平台配置 API](guides/platform-config-api.md)
- [任务工作区 TXT/LOG/Markdown 使用说明](guides/task-file-text-formats.md)
- [Web 管理多钉钉 Runtime](guides/web-managed-multi-dingtalk-runtime.md)
- [Web Secret 与环境配置](guides/web-managed-secrets-and-env-config.md)

## 运维

- [数据库迁移、旧库基线接轨与空库初始化](operations/schema-baseline-bootstrap.md)
- [Docker 部署与验收](operations/docker-deployment.md)
  - [PostgreSQL 16 与 RabbitMQ 3 升级](operations/docker-deployment.md#postgresql-16-与-rabbitmq-3-升级)
- [Runtime 多副本池](operations/runtime-replica-pool.md)
- [本机 SVN 检出](operations/local-svn-checkout.md)
- [按需代码知识库](operations/code-knowledge-on-demand.md)
- [真实环境验收欠账](acceptance-backlog.md)
- [Agent 重试与失败投递](operations/agent-retry-failure-delivery.md)
- [钉钉报告排版与分片恢复](runbooks/dingtalk-report-presentation.md)
- [Worker / Runtime 提示词版本不一致](runbooks/runtime-prompt-version-drift.md)
- [平台 Master Key](operations/platform-master-key.md)
- [钉钉测试数据重建](operations/dingtalk-test-data-rebuild.md)
- [受治理文档处理](operations/governed-document-processing.md)

## 知识库

| 需要做什么 | 入口 |
| --- | --- |
| 了解当前部署方式与服务用途 | [知识库部署说明](../knowledge/README.md) |
| 安装网页运维、构建/启停、配置计划、看进度 | [知识库运维手册](../knowledge/OPERATIONS.md) |
| 采集准备、首次全量、四小时增量、日期补采和恢复 | [同步与恢复](runbooks/knowledge-ones-hourly-sync.md) |
| 发布知识资源、角色应用授权与检索排障 | [知识治理](runbooks/knowledge-governance.md) |
| 显式重建索引、跨架构和 Qdrant 维护 | [本地向量索引](runbooks/knowledge-local-vector-index.md) |
| 重排模型升级与人工效果评测 | [检索评测](runbooks/knowledge-retrieval-evaluation.md) |
| 维护历史离线数据和分块 | [离线导入](operations/knowledge-offline-import.md)、[文本分块](operations/knowledge-text-chunking.md) |

日常运维优先使用 Web / `knowledge.sh`。旧 Compose 扩展和离线维护 CLI 仍有明确适用范围，不能与新调度器重复运行。检索预算的实现/主规格差异集中记录在[知识治理说明](runbooks/knowledge-governance.md#实现与主规格差异)；此次文档更新不改变 canonical 规范或历史验收结论。

## 验证与参考

- [MCP Inspector 开发测试](development/mcp-inspector.md)
- [ADR 状态索引](reference/decisions/README.md)
- [Docker 兼容修改的本地验证记录](operations/docker-compatibility-validation.md)（历史证据，不代替现行整套验收）

## 历史归档

工作区不再保留 `docs/archive/` 现行副本。追溯已退役决策、旧实施基线及其他历史文档时，使用 Git 历史（含曾归档的 change / evidence），不得把历史路径当作当前操作入口。

本地执行 `make docs-link-check` 检查仓库内 Markdown 文件链接；链接失败时不得通过移动文件来“隐藏”历史引用，应修正目标或明确标记为外部/历史文本。
