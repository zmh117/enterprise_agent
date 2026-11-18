# 2026-11-18 按代码刷新领域主规格

用户明确批准保留 10 个领域、按当前仓库证据刷新过时条款、关闭全部历史 active change（含未完成任务）、原样保留既有 archive，并收紧 Codex 默认只读 canonical specs。本记录是历史审计材料，不是 canonical 规范，也不是默认 Codex 上下文。

## 结果

- 继续保留既有 10 个领域主规格；按 Webhook 演进链、知识/SVN 源码问答、Runtime/门禁/MCP 等仓库证据刷新过时条款。
- 未把旧预提取、每小时整库同步、固定服务账号 Webhook、强 Bearer-only 或 Trigger 固定 Agent 写回基线。
- ONES 重排与可读性：规范仍要求授权筛选后才能作为可返回结果；重建记录承认实现可先对平台过滤候选重排再核验，不把当前实现写成已满足“重排前个人权限筛选”。
- 47 个历史 active 目录使用 `openspec archive <name> --skip-specs --yes` 原样移动；51 项未勾选任务没有补勾。
- 既有 archive（含 2026-09-16 重建记录）及全部文件保留；本次另增 47 个历史关闭目录与本记录目录。
- Codex OpenSpec 技能迁至 `.agents/skills/`，并增加 canonical 读取范围守卫；仓库入口仍为 `AGENTS.md`、`openspec/config.yaml` 与主规格导航。

## 来源与完整性

`preservation-manifest.json` 冻结关闭前 47 个来源目录的文件 SHA-256；`change-closure.json` 记录关闭路径、原任务计数与领域映射。文件摘要仅用于完整性核验，不包含原业务消息或凭据正文。

旧 delta 与当前代码冲突时，以本批次“按当前代码事实”授权修正；未能确认或仅属目标环境验收的内容不提升为当前能力。原任务文本与关闭前主规格仍可按本记录与 Git 历史追溯。

## 未完成事项

[51 项原始未勾选任务](pending-acceptance.md)保留原文。代表性欠账包括：真实 ONES 双用户/撤权与时间线完整阅读、三平台 SVN 挂载并发与长检出、Linux CI 上 MCP Inspector 实际运行阻断、Windows 分页游标连翻、MySQL/SQL Server/Oracle 真实压缩字段解码、真实钉钉/公网 Webhook 投递与生产迁移验收。本次没有顺手修改产品实现或补签现场验收。

## 关闭清单

详见 [change-closure.json](change-closure.json)。按领域主责可概括为：

| 主题 | 代表 change | 当前领域 |
| --- | --- | --- |
| Webhook 认证/路由/投递 | simplify-webhook-application-routing、bind-webhooks-to-execution-users、add-webhook-dingtalk-result-recipients 等 | channel-conversation、identity-access、business-application、execution-delivery |
| 知识入库与运维 | prepare-ones-knowledge-chunks、implement-incremental-knowledge-sync、change-knowledge-sync-interval-to-four-hours 等 | platform-operations |
| 知识检索与核验 | enable-governed-knowledge-retrieval、improve-knowledge-retrieval-ranking、verify-knowledge-hits-with-ones-timeline 等 | builtin-tool-resource、governed-api-capability、execution-delivery |
| SVN/源码问答 | replace-code-preextraction-with-on-demand-knowledge、isolate-code-knowledge-by-environment、use-docker-volume-for-svn-checkout 等 | platform-operations、builtin-tool-resource、task-file-workspace、execution-delivery、identity-access |
| Runtime/门禁/工具 | prevent-runtime-prompt-version-drift、exclude-file-reads-from-turn-budget、harden-quality-gates-and-align-current-docs、add-mcp-inspector-smoke-tests、auto-decode-compressed-database-fields 等 | execution-delivery、platform-operations、builtin-tool-resource、governed-api-capability |

## 本次验证

- `openspec list --json`：本批次 47 项不再作为 active change。
- `openspec validate --specs --strict --no-interactive`：10/10 通过。
- 主规格仍恰为 10 份；导航与 `AGENTS.md` 指向本记录。
- 摘要核验：关闭前 358 个变更文件摘要写入 preservation-manifest；归档后应与移动目录一致。
- 未运行产品完整测试套件、构建部署或真实 Provider/E2E。OpenSpec 格式通过不能替代真实环境验收。
