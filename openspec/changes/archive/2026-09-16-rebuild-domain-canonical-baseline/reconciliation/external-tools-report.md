# 工具资源与业务 Provider 领域重建报告

## 范围和结果

只编辑 `openspec/specs/builtin-tool-resource/spec.md` 与 `openspec/specs/governed-api-capability/spec.md`。前者从 1200 行重建为 411 行，后者从 493 行重建为 497 行，另吸收相关 active delta 和原 `dingtalk-mcp` 的当前有效业务合同。没有修改代码、测试、历史 archive，也没有移动 change 或删除原 `dingtalk-mcp`（由根代理集中处理）。两份均清理历史拼接注释、一次性迁移情景和旧阶段表述，保留 Requirement/Scenario 格式与简短实现/验收边界。

按 `openspec-sync-specs/SKILL.md` 的语义合并规则读取基线与相关 delta 后，以现代码/测试定义为裁决依据，而非逐字附加。此范围由原用户确认全部历史 active 关闭与按代码事实改写旧文档授权。

## 主要归并

- builtin：共享代码 Manifest、Server 固定与 Job 精确授权；Resource 草稿/验证/发布、连接和 scope 原子版本、精确拓扑创建、动态当前资源唯一解析、自定义 placement 资源角色、授权目录和不透明分页、schema 方言与分页、DB 只读/限制/账号验证、Oracle 委派和客户端构建、Redis namespace/SCAN continuation、Loki 精确 label scope/级联发现/行数限制、审计先于外部访问和维护重置。
- governed：ONES 当前身份调用/一次刷新、固定 Operation/REST/GraphQL、17 个只读 Tool 职责、九类自动收集、条件字典、人员/测试资产合同、创建/更新缺陷 mutation；钉钉当前代码固定 21 个 read 与 14 个 mutation、目标身份策略、AI 表格结构与记录操作、姓名消歧、用户批量消息、当前群消息、本人工作通知及受理/送达分层。

## 基于代码纠正的旧语义

1. ONES 不再“只发布两个只读 Tool”。`backend/app/shared/ones_tool_contracts.py` 当前包含完整基础查询/条件解析和 `ones_create_bug`、`ones_update_task`；`mcp_tool_runtime/manifest.py` 校验 mutation 的 effect/policy/operation/risk/target 元数据。
2. `ones_work_item_search` 当前输入只有 keyword/issue_type，公开 limit/cursor 与 50/500 分页链均已过时。`ones_tool_contracts.py`、`provider/graphql/collection.py`、`tools/query_services.py` 实现九类自动收集：四类测试资产 10000/200 次请求，其余五类 1000/50 次请求；每页最多 200，90 秒/8 MiB 总预算。`ones_list_testcase_modules` 与 `ones_list_issue_types` 为直接列表，不能伪造 Provider 分页。
3. `paginate-ones-work-item-search` 的模型游标绑定旧设计不再纳入 canonical；其授权隔离目的由当前调用 Principal/Job 精确授权与调用内部游标完成。相关 change 的历史任务不改写为已验收。
4. `extend-ones-mcp-query-conditions` 中“标准查询 schema/hash 永远不变”只属于引入自定义 Tool 当时兼容目标；随后自动收集确实改变列表 schema。保留“标准与自定义为独立工具、旧 snapshot drift 失败关闭”，不保留历史 schema 永久不变承诺。
5. Oracle 当前固定 `oracle_11g_v1`：11.2.0.4、AL32UTF8/AL16UTF16、64-bit 匹配架构 19c Thick。删除旧 thin/modern/FETCH FIRST 的可选合同。`database_resource_verifier.py`、`oracle_client.py`、`infrastructure/oracle_verification.py` 已实现 API 委派 tool-mcp，故删除“无论环境一律 Oracle BLOCKED”，改为必须匹配真实 Draft 验证事实；同时不声称真实 Oracle 验收。
6. 数据库专用只读账号要求保留非 local 边界；代码 `platform_config/application/service.py` 与 bootstrap 允许 `environment=local` 的特权测试账号，仍有 readonly session/probe。规范如实记录 readonly_account=false / privileged_account_allowed=true，不把本地例外写成生产默认。
7. Loki 静态 label 名称 allowlist 被语法合同取代。四种 Loki Tool 共用非空 fixed selector，追加任意合法非固定 label，同值重复固定 key 也拒绝；平台默认 10000，resource 新建默认/上限 1000，effective min，默认请求 100，不是 Job 累计预算。依据 `shared/loki_contract.py`、`domain/loki_policy.py` 与对应测试。
8. placement 不仅 cloud/edge：`shared/resource_role.py` 支持 1–64 位中文/字母数字/_.:-，是资源实例精确角色，不是授权角色；Loki 仍拒绝非空 placement。资源目录在筛选/分页前计算歧义，避免搜索隐藏重复资源。
9. 钉钉 phase-2 delta 的 18 read/旧 mutation 目录已落后。当前 `dingtalk_tool_contracts.py`、read_catalog、mutation_catalog 是 21 read/14 mutation，含三个本地 AI 表格参考工具与 sheet/field 创建更新。旧“禁止所有表结构写入”改为实际允许创建/更新但仍禁止删除。
10. 当前群消息 Tool 为 `dingtalk_send_message_to_group_by_robot`，只允许可信群来源；`dingtalk_send_robot_message` 已在 EXCLUDED 列表。私信使用显式 userId 批量 Tool，工作通知仍本人专用。旧 delta 要求保留泛化旧 Tool 的内容不采纳。依据 provider.py、mutation_catalog.py 与 test_dingtalk_mcp_runtime.py 的 group/batch/target/acceptance 测试。
11. 消息 `processQueryKey` / 工作通知 task_id 仅为受理，Intent 成功不证明最终送达。批量 Provider 过滤/限流/非法集合必须属于冻结接收者，返回 accepted/not_accepted 计数。
12. ONES 只读 GraphQL 文档集中存代码资源，但 task_update 当前存在代码内固定预检文档，故没有声称所有 GraphQL 必须独立文件；保留代码拥有与禁止动态输入的实质边界。
13. ONES create_preflight 是当前固定实现依赖，真实 Provider 未提供其可靠 ready/can_create/布局/引用合同时不可用。没有把离线替身中的成功误写为真实创建已落地验收。
14. 原 builtin `Context search returns compact relevant graph context` 没有对应当前 tool Manifest/执行器，未列为当前能力。原“Published Loki 长期 EMPTY/DEGRADED 监测”未在当前治理实现找到独立状态监测机制，未保留为已实现能力；保留实际空查询/probe与错误区分。
15. 删除“删除 Mock 服务时必须保留其他 Compose”等一次性变更指令，但保留现在不部署 ONES Mock、离线替身不得依赖真实抓取的持续边界。

## 跨领域条款移交

- 原 builtin 身份/RBAC/权限范围块（约 494–605）和原 governed 前 103 行 ONES credential/challenge/default Team/绑定生命周期，由 identity agent 归入 `identity-access`，双方已通信确认。此处仅保留 Tool 使用这些事实的边界。
- 原 builtin File MCP 认证/Service Principal/文件审计（约 968–1009）与 File MCP representation、historical recall、Workspace 目录和容量块（1103–1200）由 runtime agent 归文件领域。本文用 canonical 领域引用代替重复。
- 原 governed-external-action-confirmation 与通用确认/Outbox/claim/recovery交根代理/runtime 域；governed仅保留具体Provider前置条件、冻结目标与结果语义。
- `paginate-ones-graphql-list-tools` 的“Tool Call 时间线显示安全失败原因”交 execution 域，不在 builtin 重复。

## 当前验证

已执行并通过：

- `openspec validate governed-api-capability --type spec --strict`
- `openspec validate builtin-tool-resource --type spec --strict`
- `git diff --check -- openspec/specs/builtin-tool-resource/spec.md openspec/specs/governed-api-capability/spec.md`

本次没有执行 Provider 网络调用、数据库查询、读取真实 Secret/env、查看 archive 正文或运行真实 E2E。没有因为文档任务重复运行整个后台测试套件；所列测试文件是核对合同来源，不将历史或未执行的测试报告为本次通过。真实 ONES、钉钉与 Oracle 仍保留未验收界限，历史未勾选任务应按根代理清单原样保留。

## 观察到但未修改的代码文案残留

`frontend/src/contexts/platform-governance/presentation/credential-center-page.tsx:320` 仍出现 Last Known Good 文案，与 DirectResourceResolver 实际失败关闭行为不符。本次用户授权范围为旧文档与基线，未改 UI 代码，也不将该文案提升为 canonical 能力。
