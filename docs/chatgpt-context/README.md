# Enterprise Agent ChatGPT 上下文包

这组文档用于把当前项目录入 ChatGPT Project，支持后续架构讨论、方案设计、风险评审和 OpenSpec 变更规划。它是对当前仓库的高信号摘要，不替代源代码、迁移、ADR 或 OpenSpec。

## 快照基线

- 整理日期：2026-08-04（Asia/Shanghai）
- 仓库：`enterprise_agent`
- 分支：`master`
- 基线提交：`1eebd0d`
- Git 状态：工作区干净，本地 `master` 比 `origin/master` 领先 1 个提交
- 当前数据库迁移头：`027`
- 事实来源优先级：当前代码与迁移 > 已完成任务及验证记录 > 主规格与 ADR > 进行中的 OpenSpec 设计

OpenSpec 中的 proposal、design 和 task 代表设计意图及实施记录，不能仅因文档存在就视为运行能力已经完成。本上下文包会明确使用以下标签：

- **已实现**：当前代码或迁移中已有实现，并有测试、验证记录或运行证据。
- **部分完成**：主体实现已落地，但仍缺真实环境、浏览器、故障恢复或全量质量门验收。
- **规划中**：主要存在于 OpenSpec，不能当作当前功能。
- **现场快照**：2026-08-04 本机 Compose 状态，只代表该时点，不代表生产状态。

## 建议上传文件

建议把本目录全部 Markdown 文件一起上传，并让 ChatGPT 首先读取本文件。推荐顺序：

1. `01-project-overview.md`：项目目标、范围、技术栈和仓库地图。
2. `02-system-architecture.md`：系统分层、服务拓扑和模块职责。
3. `03-domain-model.md`：核心领域对象、关系、状态和不变量。
4. `04-runtime-flows.md`：钉钉、Webhook、Job、Tool、附件和 Delivery 链路。
5. `05-security-and-governance.md`：身份、权限、凭据、只读和数据安全边界。
6. `06-deployment-and-operations.md`：Compose、配置分层、运维和排障方法。
7. `07-implementation-status.md`：已实现、部分完成、规划中和当前风险。
8. `08-design-decisions.md`：后续设计必须保持的关键决策与防漂移规则。
9. `09-chatgpt-collaboration-guide.md`：给 ChatGPT 的协作指令与起始提示词。

## 使用方式

在新对话开始时可以发送：

> 请先完整阅读本项目上传的 `docs/chatgpt-context` 文档。后续讨论必须区分当前实现、OpenSpec 计划和待验证假设；涉及架构变更时，先说明受影响的领域边界、发布快照、授权链、数据迁移、回滚和验收证据，不要默认创建任意 URL、SQL、脚本或通用执行器。

如果讨论涉及具体实现，还应补充上传相关源文件、迁移、ADR 或 OpenSpec change。不要上传 `.env`、Master Key、Client Secret、Token、密码、模型 API Key、数据库凭据、内部消息正文或包含真实敏感标识的现场导出。

## 主要源文档

- `CONTEXT.md`：统一领域语言、关系和已澄清歧义。
- `README.md`、`backend/README.md`：运行方式与后端边界。
- `docs/adr/*.md`：受治理 API Capability 的关键架构决策。
- `docs/business-application-control-plane.md`：业务应用控制面。
- `docs/governed-api-capabilities.md`：受治理 API 能力发布与运行边界。
- `docs/unified-identity-rbac-admin.md`：统一身份、RBAC、外部身份和 Agent 发布。
- `docs/web-managed-multi-dingtalk-runtime.md`：多钉钉 Stream Runtime。
- `docs/internal-api-platform.md`：内部只读数据平台。
- `openspec/changes/*`：变更设计、任务和验证记录。

## 新鲜度约束

本包不是自动同步文件。发生以下变化后应重新生成或至少更新 `07-implementation-status.md`：

- 新增或归档 OpenSpec change；
- 新增 migration、服务、worker、队列或外部 Provider；
- 修改身份、授权、Credential Subject Policy 或业务应用发布语义；
- 修改 Agent、Application、Capability、Connection 的快照与激活规则；
- 完成真实钉钉、Webhook、ONES、模型或 Internal API Platform 验收；
- 修复当前质量基线或运行健康异常。
