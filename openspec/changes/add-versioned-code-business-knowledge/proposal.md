## Why

当前知识检索围绕 ONES 文档，无法按 MES 源码版本完整解释工单、处方、物料等对象的操作条件，也无法证明某条规则在哪次 SVN 提交发生变化。需要从用户提供的当前代码建立有证据的业务知识基线，并在每日开发更新后维护可查询、可比较、可恢复的知识快照。

## What Changes

- 纳入同一项目仓库、同一分支的三个代码角色：`set_server` 为后端、`set_web/EBR` 为工厂端前端、`set_web/JTH` 为集团端前端；排除其他前端目录。实际 SVN 地址和分支内路径在部署时配置，不从本地目录名猜测。
- 首期交付提取、入库、问答、更新闭环：工厂端覆盖工单发布、开始、报工及其处方、主配方、物料、配置和权限依赖；集团端覆盖应用启停和授权范围。按真实调用关系分析公共后端，不把集团端视为工厂端的历史分支。
- 以当前 `ones知识库/项目代码/` 的获准代码建立本地来源基线，实施导入时生成路径、编码、内容摘要及纳入/排除清单。SVN revision 初始为空；核验关联前只能称为本地基线，允许独立完成提取和问答。
- 建立对象状态、业务操作、条件规则、版本化关系、逐项证据和覆盖记录；分别保存前端限制、后端行为、需求意图及待确认事项。记录现场诊断所需数据项，实时业务数据接入属于后续阶段。
- 在内网后台通过已发布 Python Agent 和 Runtime 只读源码挂载提取候选知识包，复用平台模型、Job、沙盒、审计和预算机制；不让模型执行 SVN、Shell、直接写内容数据库或激活知识。
- 每日按 SVN revision 增量采集，以变化前后代码和反向依赖决定重新提取范围；保留中间提交及待分析状态，支持正式发布版本预构建和历史版本按需构建。
- 复用 PostgreSQL、Qdrant、Worker 和现有排队基础，代码来源及候选使用部署登记的 Runtime 来源卷和产物卷，补充不可变源码快照、知识快照成员、规则变化及构建状态。知识索引准备完成且校验通过后自动激活开发快照，失败保持旧快照并显示滞后。
- **BREAKING**：扩展知识目录/检索合同以识别代码来源和明确版本，增加完整业务操作读取与版本比较/历史追溯工具；新合同通过新 Agent/Application Publication 生效，历史 Job 不被静默升级。ONES 的现有访问模式及逐文档增量语义继续保留。
- 提供 `code-business-query` 问答 Skill 和 `extract-business-knowledge` 提取 Skill；缺少版本时询问，明确区分本地基线、最新已验证开发版本、用户指定 SVN 版本和现场部署版本。
- 管理页面提供来源配置、本地基线、每日计划、版本列表、构建进度、历史请求、失败重试、证据核验和快照回滚；普通问答展示业务解释和来源位置，不返回源码全文。

## Capabilities

### New Capabilities

无新增 canonical 领域；新增能力归入既有领域。

### Modified Capabilities

- `platform-operations`：代码来源与本地基线、SVN 增量和历史、业务知识/关系版本、索引激活及后台运维。
- `builtin-tool-resource`：代码来源授权、固定版本检索、完整规则及依赖读取、规则比较和历史追溯、普通知识问答和源码挂载授权的隔离。
- `agent-model`：提取与问答 Skill 的发布合同、证据纪律、版本询问和集团端/工厂端适用范围。
- `identity-access`：独立且可选的 Runtime 源码授权服务身份，逐次复核当前提取 Job/Invocation 和应用业务权限。
- `task-file-workspace`：Runtime 受管提取 Job 的只读来源挂载与内部候选产物边界，不使用 File Service。
- `execution-delivery`：受管代码提取 Job 的创建、源码快照授权、候选产物关联、恢复和后台历史构建准入。

## Impact

- 当前实现依据：`backend/app/modules/knowledge/`、`backend/app/shared/knowledge_tool_contracts.py`、`services/knowledge_mcp_server/`、`backend/app/python_runtime/` 及现有知识迁移、运行中心和知识管理页面。当前调度器仍执行 `sync_ones_knowledge`，当前检索核对 `current_revision_id` 并返回 `work_item_uuid`；这些不能直接替代版本化代码知识流程。
- 涉及 knowledge schema 的版本化迁移与事实源清单，知识工具 Manifest/Runtime bridge、Agent Skill 目录、受管构建 CLI/Worker、Runtime 来源挂载与产物回收、管理 API/Web、测试和运维说明。源码原目录只读，提案阶段不导入数据库、不运行迁移、不接通 SVN、不创建每日自动任务。
- 不引入图数据库、状态机生产执行引擎、通用代码插件框架、任意表达式执行器或全历史逐提交全库重建。首期不实现现场 MES 数据查询、自动根因判定、源码全文问答展示、SVN post-commit Hook 或跨项目多仓库编排。
- 首次基线和新增语义覆盖需要可审查业务样本；来源/结构/摘要校验不代替业务正确性验证。目标 SVN、真实模型、实际内网后台及生产部署版本绑定的验收与本地确定性测试分别记录。
