> 实施状态（2026-11-09）：用户已调用 openspec-apply-change 授权实施。以下“仅设计／不改代码”等描述是此前提案阶段的边界；本轮实施进度与验证以 tasks.md 和 implementation-evidence.md 为准，尚未部署的设计不视为线上能力。

## Why

业务目标是让同一个问答 Agent 先查已有知识，缺少适用证据时直接读取检出的 SVN 代码、查询提交记录，再回答并按版本缓存结论。额外复制封存源码和派发独立提取 Agent 增加了目录、任务与调度成本；采用受管工作副本和分析期间的更新互斥即可满足当前需求。

## What Changes

- **BREAKING**：退役全量/定时业务预提取、整包候选发布和缺版本触发构建的入口；旧候选不兼容导入，不影响 ONES 数据。
- 同一个问答 Agent、同一个 Job 完成“检索 → 判断证据 → 必要时更新/读代码 → 校验缓存 → 回答”，不派发独立提取 Agent、子 Job 或后台模型调查；缓存失败需明确告知，不伪称已保存。
- 直接将现有受管检出目录只读挂给 Runtime A/B，不生成额外源码副本、按版本快照目录或封存清单。工作副本可在分析结束后继续更新。
- 复用 `knowledge-mcp` 和 `knowledge-sync` 提供受控 `update/info/log/diff/blame` 及操作状态工具。Runtime 发起请求，执行器实际运行 SVN；模型不直接获得 Shell、SVN 凭据或写源码权限。
- `update` 显式更新/确认已登记工作副本到确定 revision，并为当前 Job 取得共享读取占用。同一目录同一版本允许多个分析并发；update 必须取得独占写权限，等待全部读取结束，更新期间不允许读取，且任何修改操作之间不得并发。
- 用户提问必须带 SVN 数字版本。先查相等版本；缺适用证据时查同仓库/分支最近更高版本，结果只作线索，必须核验用户指定版本的代码后才能回答和缓存。正常未命中与依赖失败分开处理。
- 每次有效问答都在 PG 保存带用户 SVN 号的业务回答记录，包含缓存命中。新的受支持知识经服务端校验保存后，由现有 Worker 增量分块、Embedding、写 Qdrant；重复命中不重复编码，不开放通用数据库写入。
- **BREAKING**：按 [PostgreSQL 表结构](postgresql-schema.md) 重建代码领域：10 张代码专用表复用共享文档/分块/索引层，退役 20 张旧代码表；清理旧代码专属行，不兼容旧候选，不删除 ONES 或已有检出文件。明确区分 SVN 版本、答案修订和每次问答记录。
- 新建知识库先选 ONES/代码类型并分开配置；删除旧“已登记源码快照”“mes-code · SVN 与更新计划”及顶层代码预提取面板。将 SVN 地址、检出目录绑定、PG/Qdrant、分块/Embedding/增量索引集中到代码知识库配置，支持空库创建与发布。
- 默认复用现有受管 PostgreSQL、Qdrant、Embedding 和重排服务；代码集合独立，查询先执行权限/版本过滤再重排，不把 ONES 只读外部连接自动升级为可写目标。
- 答案注明 SVN 版本；缓存保存相对路径、行号、文件摘要和历史操作证据，不依赖检出目录一直停留在原版本。
- Windows、macOS、Linux 统一由 Linux 容器执行 SVN，只在部署层映射宿主目录。保留已有开源 SVN MCP 的候选评估，以实际适配成本决定复用，当前不安装依赖。

## Capabilities

### New Capabilities

无新增顶层规范领域。

### Modified Capabilities

- `builtin-tool-resource`：代码来源授权、必填版本、相等版本优先与较高版本线索、更新/历史工具、操作状态及受控答案缓存。
- `execution-delivery`：同一问答 Job 内的源码只读能力、有效目录占用、工具权限及证据提交；不新增模型执行链。
- `platform-operations`：知识库类型与配置、检出目录绑定、读写互斥、每次问答记录、增量分块/Embedding/索引、共享重排、三平台挂载和旧入口退役。

## Impact

2026-11-09 核对：`code_source_grant.py` 仍绑定 `code_build/code_unit`、专用服务账号及旧源码目录；Runtime 源码 hook 只允许文件工具并校验整包候选。Compose 当前分别挂载检出根与旧源码根，尚未让两个 Runtime 直接只读检出目录。新流程需明确修改这些实现，不能只更换提示词。

`code_svn.py` 已有受控 CLI，日志仍使用 `--with-no-revprops`，diff 仅为摘要；现有浏览/检出可复用。实现需增加受管工作副本 update、完整历史查询、跨 Runtime 占用和恢复，以及答案保存合同。当前 canonical 仍要求冻结工具和拒绝 Shell；本变更只增加固定工具及受控源码读取，不放开任意命令。

涉及知识模块、Knowledge MCP、Runtime 路径守卫/执行收尾、Compose、管理页面、迁移及相关测试。复用 PG、Qdrant 和现有 Worker；代码与 ONES 保持独立来源、收录及集合。新增合同需要正式发布，不改写旧 Job 的冻结权限。

页面核对：当前新建表单选择已有 KB/READY 索引，旧源码面板仍独立存在；这些入口需改造。当前重排接口没有 ONES 专属字段，现有代码检索也已接入 RerankPort，可复用模型服务，但新问答与索引链路仍待实现。

本变更只交付 OpenSpec；本轮不修改应用代码、数据库、挂载或容器，不启动模型。旧候选/旧源码数据的退休在实施时先清点引用，未完成验收不补记为通过。

数据库设计已按现有迁移和增量处理代码核对；新表字段、PK/FK/CHECK、索引、保存/并发事务、共享字段调整和逐表退役清单见 [postgresql-schema.md](postgresql-schema.md)。旧 sync_candidate 为 ONES 采集设计，代码派生使用 code_index_task；文档修订区分 import/code_analysis 来源，不创建虚假导入批次。这些为待实现合同，尚未执行数据库迁移。
