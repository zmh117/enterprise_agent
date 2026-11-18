# 当前主规格导航

本目录的以下 **10 份 `spec.md`** 构成唯一 canonical baseline，最近一次按 2026-11-18 当前代码刷新（承接 2026-09-16 领域重建）。本页只负责领域定位；代码实现、测试覆盖与目标环境验收分别判断。

| 领域 | 默认读取范围 |
| --- | --- |
| [identity-access](identity-access/spec.md) | 内部用户、登录与Session、角色授权、外部身份、Provider凭据与Principal |
| [agent-model](agent-model/spec.md) | Agent草稿和发布、模型连接、Skill配置、Workflow配置资产 |
| [business-application](business-application/spec.md) | 应用组合、策略、Tool子集、发布激活与运行接线 |
| [channel-conversation](channel-conversation/spec.md) | Connector、钉钉与Webhook入口、会话、消息与附件接收 |
| [document-file-processing](document-file-processing/spec.md) | Docling Profile、OCR、处理运行、并发槽位与派生表示 |
| [execution-delivery](execution-delivery/spec.md) | Job、Runtime、工具事件、审计、重试、Delivery与外部操作确认执行 |
| [builtin-tool-resource](builtin-tool-resource/spec.md) | Resource、DB/Redis/Loki只读工具、技术验证、资源目录、目标解析与Knowledge MCP目录/检索 |
| [governed-api-capability](governed-api-capability/spec.md) | ONES和钉钉业务MCP、查询分页、受治理外部写操作与Provider合同 |
| [platform-operations](platform-operations/spec.md) | Compose、Schema、Secret、运行配置、就绪、质量门禁、知识内容/索引/受管同步与规范治理 |
| [task-file-workspace](task-file-workspace/spec.md) | Workspace、File/Version、Manifest、文件准入、工作集、Sandbox、提交与生命周期 |

普通任务先按上表读取相关领域，只有跨越责任边界时才补读邻接领域。不要默认递归读取整个目录或 `openspec/changes/`。

## 旧能力的当前归属

| 旧主规格或delta名称 | 当前领域 |
| --- | --- |
| dingtalk-mcp、dingtalk-mcp-tool-suite、dingtalk-targeted-user-message | governed-api-capability |
| governed-ones-bug-create、governed-ones-task-update | governed-api-capability |
| builtin-tool-resource中曾混放的ONES查询 | governed-api-capability |
| governed-external-action-confirmation | execution-delivery |
| 工具响应时间线与安全失败摘要 | execution-delivery |
| 原工具域中的身份与文件规则 | identity-access、task-file-workspace，按实际责任分配 |

后续新需求作为这些领域的明确增量处理。确需新增领域时先明确修改基线与导航，不根据历史文件夹名称自动创建主规格。

## 历史与验收

2026-09-16 的 29 个、以及 2026-11-18 的 47 个历史 active change 已归档关闭，原任务勾选与文件内容保留。关闭不等于全部实现或验收完成；未完成任务与真实环境验收欠账单独记录，不得补勾。

需要追溯重建时，显式读取 [2026-09-16 重建记录](../changes/archive/2026-09-16-rebuild-domain-canonical-baseline/README.md) 或 [2026-11-18 重建记录](../changes/archive/2026-11-18-rebuild-domain-canonical-baseline/README.md)；普通任务不自动读取该记录或其他 archive。既有 archive 保持原路径与原内容，不能覆盖本目录主规格。
