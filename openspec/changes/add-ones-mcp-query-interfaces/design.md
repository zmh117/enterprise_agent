## Context

当前 `ones-mcp` 已具备独立 `business-principal-jwt`、默认 Team、个人 ONES Credential、最多一次 Token refresh、Publication/Application/Job 快照校验和 MCP 审计，但业务查询面只有 `ones_work_item_search` 与 `ones_list_project_role_members`。前者调用仓库自定义 `/project/api/project/items/graphql`，不能直接对应本地抓取中真实 ONES 使用的 Team 路径和固定 `t` 查询类型；Provider HTTP Client 也明确拒绝 query string。

本地 `ones_mock/ones/` 保存了真实环境只读调用的契约参考，其中 GraphQL、REST、登录和静态筛选字典混合存在。该目录被忽略且可能包含真实业务响应，只能用于人工核对方法、路径、GraphQL 文档、变量和必要响应字段，不能成为运行时资源或被复制进测试 fixture。

## Goals / Non-Goals

**Goals:**

- 用固定代码资产表达项目、迭代、工作项、人员和测试资产的基础只读查询。
- 将 GraphQL 文档统一存放在 `provider/graphql/documents/`，将非 GraphQL 接口保留为精确 REST Operation。
- 让 Tool 只接受业务筛选参数，Team、用户、Token、URL、Header、GraphQL 文档和固定 `t` 值全部来自已验证 Principal 与代码。
- 对真实 ONES 响应做白名单规范化、数量/字符串/字节边界和明确的截断投影。
- 保留现有工作项搜索 Tool Schema，并允许新 Tool 通过正常 Agent/Application Publication 链路逐步启用。

**Non-Goals:**

- 不定义“响应时间”等统计口径，不增加统计聚合 Tool。
- 不增加或修改 Agent Skill。
- 不增加写操作、任意 GraphQL/HTTP 执行器、动态 Query Library、租户字段字典管理或跨 Team 探测。
- 不把 Mock 通过描述为真实 ONES 兼容验收；真实环境只读探测仍是单独的部署验证。

## Decisions

### 1. MCP Tool 按稳定业务能力建模，Provider Operation 按真实接口建模

新增 Tool identifier：

- `ones_search_projects`
- `ones_list_project_sprints`
- `ones_list_issue_types`
- `ones_query_work_items`
- `ones_get_work_item_detail`
- `ones_list_work_item_messages`
- `ones_search_team_users`
- `ones_list_testcase_libraries`
- `ones_list_testcase_modules`
- `ones_list_test_plans`
- `ones_query_test_cases`
- `ones_get_test_case_detail`

保留 `ones_work_item_search` 和 `ones_list_project_role_members`。Provider 层可以为一个 Tool 固定组合多个接口，也可以让一个规范化工作项 Tool 根据已校验的业务筛选选择代码拥有的通用或迭代 GraphQL Operation，但不会暴露 operation code、`t`、URL 或 GraphQL 文本。

相比“一份抓取一个 Tool”，这种边界避免让 Agent 理解 ONES 前端内部查询名；相比“通用 GraphQL Tool”，它保持固定 Schema、审计、授权和响应解析。

### 2. GraphQL query type 使用结构化固定参数，不放宽任意 URL

`OnesProviderHttpClient` 增加可选的结构化 query 参数，并对 key/value 采用保守字符和长度校验后使用标准 URL 编码。GraphQL Operation 声明固定 `path_template=/project/api/project/team/{team_uuid}/items/graphql` 与固定 `query_type`；迭代 REST Operation 声明固定 `t=sprint`。Team UUID 只从已验证 Principal 上下文取得，Tool Input 不能覆盖。

HTTP Client 继续拒绝调用方直接在 path 中传入 `?`、fragment、scheme、host 或绝对 URL，继续禁用代理、拒绝重定向并执行 timeout、状态码和响应大小限制。

### 3. 使用小型共享只读执行基类，具体 Tool 仍为代码拥有的实现

现有两个 Tool service 重复 Principal resolve、审计、Provider attempt、一次 refresh 和 Credential mark-used。新增 `BaseOnesQueryService` 固化这条安全执行骨架，具体 Tool 只实现输入验证和固定 Provider 调用。每个 Tool 仍有明确类、identifier、Schema 和实现函数，基类不接受动态 URL、GraphQL、operation code 或任意回调输入。

输入 Schema 的唯一共享事实源放在无副作用的 ONES Tool contracts 模块，由 `ones-mcp` 和平台 `MCP_TOOL_MANIFEST` 共同导入，避免新增十余个 Tool 后出现 Manifest/服务端 Schema 漂移。

### 4. 输出只保留回答基础查询所需的规范化字段

- 项目：UUID、名称、归档/样例状态、负责人和状态分类。
- 迭代：UUID、名称、项目、时间区间、状态、进度。
- 工作项：UUID、编号、名称、项目、类型、状态、负责人/处理人、迭代、创建/更新时间、子任务计数；详情额外返回有界描述和有界关联摘要。
- 时间线：事件 UUID、类型、发送时间、参与者显示信息和有界纯文本；附件 URL、富文本原文、Token、Avatar、电话、邮箱和内部扩展不返回。
- 人员：UUID、姓名；项目角色成员沿用现有角色与姓名输出。
- 测试资产：库、模块、计划、用例的 UUID、名称、状态、负责人、路径和有界步骤摘要。

所有输出包含 `untrusted_data=true`。列表输出包含 `total`、`returned`、`truncated`，只有抓取契约明确提供 continuation cursor 的接口才返回 `next_cursor`；不能从首屏推断“全部”。Provider 原始响应和 GraphQL 文档不进入模型可见结果，审计保存有界规范化请求/结果摘要，不保存认证材料或无界消息正文。

### 5. 现有 Tool 保持 Schema 兼容，新 Tool 通过新 Publication 启用

`ones_work_item_search` 保持现有 `keyword + issue_type + limit` 输入与 `number/name/type` 输出，由服务端把稳定 `demand|task|defect` 映射为当前项目/Team 中查询得到的工作项类型，再执行真实 `group-task-data` 查询。若类型无法唯一解析则失败关闭，不猜 UUID。

新增 Tool 进入代码 Manifest 后，不自动修改旧 Agent/Application Publication。管理员需要选择新 Tool、发布 Agent、在业务应用中选择新 Agent Publication 与 Tool 子集、发布并激活，再由新 Job 冻结使用。

### 6. Mock 只模拟精确接口形状和安全负向路径

`ones_mock` 扩展合成项目、迭代、消息、人员、测试库/模块/计划/用例 fixture，并按固定 `t` 与请求变量返回真实形状的有界结果。测试覆盖无效固定 query type、错误 Team、401/refresh、403、超大响应、非法结构、分页截断和敏感字段不投影。不得从 `ones_mock/ones/` 复制任何真实响应值。

## Risks / Trade-offs

- [风险] 抓取只覆盖当前 ONES 版本和首屏分页参数。→ 解析只要求必要字段、忽略额外字段；未确认 continuation 合同时明确返回 `truncated`，不伪造翻页协议。
- [风险] 真实租户的工作项类型名称或 UUID 不一致。→ 通过项目工作项类型查询动态解析，Tool 不硬编码租户 UUID；歧义时失败关闭。
- [风险] 详情和时间线响应包含大量或敏感字段。→ Provider 响应受字节上限保护，Parser 白名单投影并对正文、事件数和字符串长度设限。
- [风险] 新 Tool 数量增加 Publication 配置和测试范围。→ 使用共享安全执行基类与共享输入契约，但保持每个 Tool 的显式业务类和固定实现。
- [风险] Mock 与真实 ONES 仍可能存在 Header、GET body 或响应差异。→ Mock 验证只作为仓库闭环；上线前执行经授权、只读、脱敏的真实环境探测。

## Migration Plan

1. 先部署兼容旧 Tool 且包含新 Provider/Tool/Mock 的代码和 Manifest。
2. 重建并启动 `ones-mcp`、API/Worker 与独立 Mock，验证现有 Publication/Job 路径不发生 Schema drift。
3. 创建并发布选择新增 Tool 的 Agent Publication，再显式发布和激活业务应用。
4. 使用新 Job 验证项目→迭代→工作项和测试资产查询链；真实环境验证只记录接口结果类别、数量、耗时和 correlation，不记录凭据或原始业务正文。
5. 回滚时恢复上一代码版本并把业务应用切回旧 Publication；不可变旧快照不修改。

## Open Questions

本 change 无待确认的统计语义；统计 Tool 和 ONES 查询 Skill 留给后续独立 change。
