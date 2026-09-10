## Context

## 第四阶段：Runtime 提示词版本回归修复（2026-09-10）

- Worker 默认上下文仍声明 Prompt v5，而 ONES 结果只读工具接入后 Runtime 观测声明 v6；Worker 在接收 tool_contract_observed 时严格比较失败。版本定义移至两侧已共享且都被镜像复制的 app.shared.tool_contract，不通过放宽校验兼容不一致组件。
- 协议拒绝仍使用 runtime_protocol_error，但安全消息须明确代码固定的拒绝原因；工具契约差异包含事件序号、固定字段名和安全期望/实际值。仅固定格式的 Prompt 版本及 SHA-256 可显示值，构建身份只显示匹配状态；无效字段不回显。未通过校验的 Runtime 事件不得进入已验证事件账本。
- 复用现有 Job 错误步骤、error_message、execution_summary.failure_summary 与失败码，运行记录直接展示安全原因，不新增审计主账或伪造 Tool Call。默认上下文必须通过 Runtime 真实观测构造与 Worker NDJSON 接收链回归，同时测试不一致及恶意字段仍失败关闭。
- 本次只部署和验证本地受影响组件；原失败 Job 保持历史事实，不自动重跑或修改 Publication/环境配置，真实 ONES 验收仍待办。

## 第三阶段：现场接口兼容与 Mock 下线

- 以现场文档中的字段、类型、单位和请求投影核对所有已注册 ONES Operation；文档中未被当前工具使用的接口仅登记，不新增工具或扩大写权限。样例的业务值、认证头和身份信息不得复制进测试，回归使用独立合成值保持结构与单位一致。
- 已复现迭代 `progress=10000000` 被 0..100 原值校验拒绝；百分比在 Provider 边界按 100000 的定点比例转换，公开输出允许保留小数。REST 迭代日期与测试用例创建时间按各接口明确的秒级单位处理，不依据长度混猜所有时间字段。
- GraphQL 查询必须检查顶层 errors；字段校验错误包含代码固定的字段路径、期望约束与实际类型/空值/长度等安全形状，不带字段原值或上游原始错误消息，复用现有 error/error_code 审计和时间线。
- 用例列表必须与其他 bucket 使用相同页完整性校验，不能在裁剪后推进原页尾 cursor；现场文档中 count 与保留条目不一致的节选不能作为放宽完整性校验的依据。
- 删除 Mock 运行容器、Dockerfile 与可部署入口，测试替身移至 tests/support 且不读取环境 Provider 配置；现场文档保留，原独立 Compose 只删除 ones-mock 服务，其余数据库/Redis 服务、项目名称、脚本入口和数据卷不变。用户最终确认保留修复，但不改其他配置：恢复 .env.example、本地 .env 和主 Compose 原连接配置，ones-mcp 保持原启动/健康校验，不引入未配置上游模式或可选 profile。Compose 验收移除已删除 Mock 的模拟身份注入与调用，结果明确记录 local_non_ones 范围及跳过项，不修改已有身份/凭据数据，也不连接真实 ONES。

## 第二阶段决策（2026-09-09 用户已确认，替代本文第一阶段设计）

- 官方依据：https://docs.ones.cn/project/open-api-doc/graphql/introduction.html#分页 。bucket pagination 支持 limit（替代 first）、after、hasNextPage、endCursor、unstable；同一查询必须保持过滤/排序不变，游标只在调用内暂存。totalCount 不能独立证明查询完整。
- 覆盖九个 GraphQL 列表，含旧关键词搜索；limit 改为可选总量上限，默认/最多 1000；Provider bucket 每批最多 200，移除内层 51/101/201 及额外祖先扩展，避免游标与结果裁剪不一致。直接完整列表只读取一次并有界截取，不伪造 Provider 分页支持。
- 自动收集器置于 ONES 服务内，完整收集失败关闭；总请求次数最多 50、收集时间预算 90 秒、规范化结果最多 8MiB，另受既有单页 HTTP 超时/字节上限和 Job 总超时约束。1000/调用方上限仍有后续时返回明确 truncated 和 pagination_limit_reached；重复 UUID/编号、空续页、游标不前进、unstable 和多 bucket 返回稳定中文错误，不把部分数据标记成功。
- Runtime 新增专用 ONES 结果 bridge，保留冻结 input schema/授权检查和 MCP call 关联；仅九个集合结果物化，其他详情/REST/写工具保持原契约。ONES 进程不能直接写 Runtime 路径；bridge 通过现有原子预算预留器创建 work 下只读 Markdown（内含 JSON 数据），返回文件路径、数量、完整性和读取提示，不向模型重复发送全量正文。
- 只有冻结这些工具的 Job 派生 Read/Glob/Grep，不能因此增加 Write/Edit、文件提交、跨 Job 访问或 Bash。文件写入失败回滚预留，成功/失败/取消/超时和恢复扫描使用原 Job Sandbox 清理生命周期。中间文件清理不删除独立审计事实，也不自动形成持久 File Version。
- 时间线展示服务端已有安全 error/error_code，兼容对象和 JSON 字符串，并优先显示 returned 而非把 total 当成本页条数。不显示原始 Provider body、认证 Header 或堆栈。Provider 调用失败继续持久化根 Tool Call FAILED 和安全原因。
- 新输入契约和 Prompt 派生工具改变需重建相关组件并重新发布；历史 Publication/Job 不静默升级。旧公开 cursor 模块及其断言被自动分页测试替代；真实 ONES 未验收仍明确列为待办。

以下内容为第一阶段历史决策，不再定义第二阶段行为。

当前 ONES MCP 有八个除 `ones_work_item_search` 外的 GraphQL 列表 Tool。它们都返回有界数组和 `truncated`，但公开输入均不能提交 cursor。五类 `buckets` Operation 已能取得 `pageInfo.endCursor/hasNextPage`，其中项目、测试计划和测试用例文档仍把 `after` 固定为空字符串；工作项与测试库虽把 Provider cursor 投影为 `next_cursor`，也没有可信公开续页入口。工作项类型和测试模块 Operation 返回不带 `pageInfo` 的直接完整列表，Parser 仅在本地切片。

现有 `ones_work_item_search` 已实现 Job/授权/身份/查询绑定的平台不透明 cursor 和 500 条累计上限，可以复用安全模型，但不能复用其固定关键词/类型 request binding。所有新 schema 仍受 Publication/Application/Job 冻结约束；真实 ONES 行为必须与 Mock 分开验收。

## Goals / Non-Goals

**Goals:**

- 让所有当前会产生截断的 ONES GraphQL 列表 Tool 都能从第一页安全续查到终页或 500 条累计上限。
- 保留工具现有业务筛选、字段投影和单页上限，不把 51/101/201 统一成一个无业务依据的数字。
- 使用同一个通用游标绑定模型，拒绝跨 Tool、Job、用户、应用、授权、schema、外部身份、Team 和查询复用。
- 对 Provider 原生游标与无游标直接列表分别采用可验证的 continuation，并保持模型不可见原始 Provider cursor。
- 让 `total/returned/cumulative_returned/truncated/pagination_limit_reached/next_cursor` 语义在这些 Tool 中一致。

**Non-Goals:**

- 不修改详情 Tool、REST 列表 Tool、写 Tool 或 `ones_work_item_search`。
- 不提供无界导出，不把单条分页链累计上限提高到 500 以上。
- 不新增任意 GraphQL、动态 Operation、调用方可控 URL/Header/Team/Provider cursor。
- 不承诺无 Provider cursor 的直接列表在集合变化时无缝续页；变化时明确失败并要求重查。
- 不以 Mock 结果替代真实 ONES 的分页、计数和游标稳定性验收。

## Decisions

### 1. 按工具保留单页上限，统一分页分页协议而不是统一数字

公开上限保持不变：项目、工作项类型、复杂工作项、测试库和测试计划为 100；测试模块和测试用例为 200。GraphQL 文档中的 101/201 继续作为相应集合的内层保护，`work_item_search` 的 51 不在本 change 修改范围。所有 `buckets` Operation 的实际页大小由代码构造的 `$pagination.limit` 决定，固定 `after: ""` 改为只接收服务端解码后的 Provider cursor。

备选方案是统一为 50；它会无必要降低已有测试资产查询能力，也不能解决无法续页的问题，因此不采用。

### 2. 通用游标支持 provider 与 snapshot-offset 两种固定模式

新增通用 ONES GraphQL 列表游标，位置只允许两种代码选择的结构：

- `provider`：保存原始 Provider `endCursor` 和此前累计返回数；适用于项目、复杂工作项、测试库、测试计划和测试用例。
- `snapshot-offset`：保存下一偏移、整个有序 UUID 集合的摘要和此前累计返回数；适用于工作项类型与测试模块。续页时重新执行同一固定只读 Operation，集合摘要不一致则返回游标已失效。

游标 purpose 包含精确 Tool identifier；request hash 使用去除 `cursor` 后的全部规范化业务参数；上下文继续绑定 Job、内部用户、业务应用、Agent/Application Publication、授权 hash、Tool input schema hash、ONES 外部身份和 Team。

备选方案是把 Provider cursor 直接返回给模型；它无法在 Provider 调用前阻止跨查询与跨执行主体复用，因此不采用。对直接列表伪造 Provider cursor 也没有接口证据，不采用。

### 3. 分页服务层统一生成公开结果

新增分页 GraphQL 查询基类，在解析 Principal 后解码 cursor，将内部 Provider cursor 或 offset 注入固定 Operation，并在响应后统一：

- 移除内部 continuation 字段；
- 计算本页 `returned` 和链路 `cumulative_returned`；
- 当 Provider/本地集合仍有后续且累计小于 500 时签发平台 `next_cursor`；
- 当累计达到 500 且仍有后续时返回 `pagination_limit_reached=true` 且不签发 cursor；
- 当报告有后续却缺少合法 continuation、返回空页但仍称有下一页、或 snapshot 集合发生变化时失败关闭。

自定义选项工作项查询仍先按当前 Team 字典验证字段和值，再进入相同分页基类；cursor request binding 使用调用方规范化参数，不使用内部转换出的 Provider filter key。

### 4. Provider Parser 必须按累计位置解释 pageInfo

所有 bucket Parser 把此前累计返回数传给共享 `page_items`，避免终页仍因 `totalCount > 当前页 count` 被错误标记为截断。`hasNextPage` 是 Provider continuation 的主要事实；`totalCount` 继续作为 Provider 报告值展示，但不能单独替代游标终止条件。

对于 `preciseCount=false` 的 Provider Operation，不把 `totalCount` 宣称为权限过滤后的精确总数；完整性由 `hasNextPage=false` 或平台累计上限决定。

### 5. Schema 变化只通过新 Publication 生效

八个 Tool 的 input schema 新增可选 `cursor`，output schema新增 `cumulative_returned` 与 `pagination_limit_reached`，并将公开 `next_cursor` 上限统一为 4096。代码 Manifest schema hash 随之变化。旧 Publication、旧 Job 和旧授权快照不自动升级，也不得放宽 drift 失败关闭。

## Risks / Trade-offs

- [真实 ONES 对某些内部 GraphQL 文档的 `$pagination.after` 行为与 Mock 不同] → 保持固定 Operation 和现有查询结构，补齐请求/响应测试，并把真实只读首/续/终页作为独立验收门槛。
- [直接列表在两次调用之间变化] → cursor 保存有序 UUID 集合摘要，变化时失败关闭，不返回可能重复或遗漏的页面。
- [直接列表每页都需重新读取完整 Provider 响应] → 仍受现有 1 MiB Provider 响应限制和 500 条平台累计上限保护；若将来 Provider 提供原生 cursor，再通过独立 change 切换。
- [schema hash 更新导致旧 Job drift] → 只通过重新发布 Agent/Application 启用新 schema，历史快照保持不可变。
- [固定内层 101/201 与 Provider 外层 page size 语义漂移] → 测试同时断言固定文档、实际 `$pagination.limit/after` 和 Parser 输出；真实环境验收记录每页 count、hasNextPage 和 cursor 前进事实。

## Migration Plan

1. 更新 delta spec、共享 Tool schema、通用游标和 Provider Operation/Parser。
2. 更新合成 Mock 与回归，覆盖每种分页模式、终页、500 上限、篡改/跨上下文和集合漂移。
3. 严格校验 OpenSpec，运行 ONES MCP、Manifest、Principal、Runtime、Mock 和静态检查。
4. 重建并替换本地 `ones-mcp` 及依赖共享 Manifest 的服务，核对容器内关键文件和 Tool schema。
5. 重新发布 Agent 与业务应用后，以新 Job 在真实 ONES 对每类 Provider cursor Operation 完成只读首/续/终页验收；未完成前只标记本地 Confirmed-current。

回滚时恢复旧代码并重新发布旧 schema 的 Agent/Application；已经冻结新 schema 的 Job 不静默降级，要求重新发起。

## Open Questions

无。
