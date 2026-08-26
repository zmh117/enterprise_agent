## ADDED Requirements

### Requirement: ONES MCP 基础查询必须使用固定业务 Tool
系统 SHALL 由代码 Manifest 提供项目、迭代、工作项类型、工作项查询、工作项详情、工作项时间线、Team 人员、项目角色成员、测试库、测试模块、测试计划和测试用例的只读 ONES MCP Tool。每个 Tool MUST 具有稳定 identifier、固定输入 Schema、有界输出和明确只读语义，且 MUST NOT 接受 Team、用户、Token、URL、Header、GraphQL 文档、GraphQL operation code、固定查询类型或任意 Provider 请求报文。

#### Scenario: Agent组合查询最新迭代工作项
- **WHEN** 新 Job 冻结并获准调用项目、迭代、工作项类型和工作项查询 Tool
- **THEN** Agent 可以用前一个 Tool 返回的项目、迭代和类型 UUID 构造后续业务参数
- **AND** `ones-mcp` 从已验证 Principal 解析默认 Team 和 Provider Credential，不接受 Agent 覆盖

#### Scenario: Tool输入提供任意GraphQL
- **WHEN** Agent 或客户端在任一 ONES Tool 参数中提供 URL、Header、Token、GraphQL 文档、operation code 或固定查询类型
- **THEN** 输入 Schema 或服务端校验拒绝整个调用且不连接 Provider

### Requirement: ONES GraphQL与REST契约必须保持代码拥有和协议精确
系统 MUST 将 ONES GraphQL 文档作为集中存放的只读代码资源，并为每个 GraphQL Operation 固定 Team 路径模板、查询类型、变量构造和响应 Parser。非 GraphQL 的迭代、时间线、用户和项目角色成员接口 MUST 使用其真实固定 HTTP method、path、query 和 JSON body；系统不得把这些接口伪装为 GraphQL，也不得提供任意 HTTP 执行器。

#### Scenario: 执行固定GraphQL查询
- **WHEN** 已授权 Tool 执行代码注册的 GraphQL Operation
- **THEN** Provider 请求使用当前 Principal 的默认 Team、代码固定的 `t` 值、集中存放的 GraphQL 文档和服务端构造变量
- **AND** Tool 参数不能改变这些接口事实

#### Scenario: 执行非GraphQL迭代查询
- **WHEN** 已授权 Tool 查询指定项目的迭代列表
- **THEN** Provider 请求使用代码固定的 REST method、项目路径、`t=sprint` 和固定 JSON body
- **AND** 请求不经过 GraphQL Registry

#### Scenario: Provider路径包含调用方query string
- **WHEN** 非代码固定路径或 Tool 输入试图携带 query string、fragment、scheme 或 host
- **THEN** HTTP Client 在外部连接前拒绝请求

### Requirement: ONES基础查询输出必须有界、规范化并披露覆盖范围
系统 MUST 只向 Agent 返回回答基础查询所需的白名单字段，限制列表数量、字符串长度、描述和时间线正文大小，并在所有结果中标记 `untrusted_data=true`。列表 Tool MUST 返回总数或已知计数、实际返回数和 `truncated`；只有 Provider 契约明确支持 continuation 时才可返回 `next_cursor`，系统和 Agent不得把截断结果描述为全部数据。

#### Scenario: 工作项查询结果超过边界
- **WHEN** Provider 表示仍有更多工作项或返回数量超过 Tool 上限
- **THEN** Tool 只返回上限内的规范化工作项并设置 `truncated=true`
- **AND** 不把首屏结果描述为全部命中

#### Scenario: 时间线包含富文本和认证链接
- **WHEN** Provider 时间线事件包含富文本、附件 URL、Avatar、电话、邮箱、Token 或其它非必要字段
- **THEN** Tool 只投影有界纯文本、事件类型、时间和必要参与者显示信息
- **AND** 模型结果和审计均不包含认证材料或附件访问参数

#### Scenario: Provider返回额外字段
- **WHEN** 真实 ONES 在固定查询所需字段之外返回扩展或租户自定义字段
- **THEN** Parser 忽略额外字段并校验所有必要字段的类型和边界
- **AND** 必要字段缺失或非法时调用以稳定 Provider schema 错误失败

### Requirement: ONES工作项查询必须支持项目迭代与时间范围基础筛选
`ones_query_work_items` SHALL 支持有界关键字、项目 UUID、迭代 UUID、工作项类型 UUID、状态 UUID、稳定状态分类 `to_do|in_progress|done`、处理人 UUID、创建时间范围和 limit 的代码拥有组合。服务端 MUST 选择固定已注册的通用或迭代 GraphQL Operation，并 MUST NOT 将筛选值拼接进 GraphQL 文档或 Provider URL。

#### Scenario: 查询迭代内已完成工作项
- **WHEN** 调用参数包含一个已解析项目、迭代、工作项类型和状态分类 `done`
- **THEN** Tool 使用固定迭代工作项 Operation 构造变量并返回匹配工作项的规范化摘要

#### Scenario: 查询创建时间范围
- **WHEN** 调用参数包含合法起止时间且结束时间晚于开始时间
- **THEN** Tool 将时间转换为 Provider 所需格式并使用固定通用工作项 Operation 查询

#### Scenario: 筛选组合无固定Operation支持
- **WHEN** 调用参数组合不能由已注册 Provider Operation 精确表达
- **THEN** Tool 返回稳定输入错误且不删除筛选条件、不扩大范围、不改用相邻查询

### Requirement: ONES测试资产查询必须保持库模块计划和用例边界
系统 SHALL 分别提供测试库、库内模块、测试计划、按模块或计划查询用例以及用例详情的只读 Tool。按模块查询 MUST 同时绑定测试库和模块，按计划查询 MUST 绑定测试计划；系统不得猜测库、模块或计划 UUID，也不得把测试资产查询混入普通工作项类型。

#### Scenario: 按模块查询用例
- **WHEN** 调用包含明确测试库 UUID、模块 UUID 和 limit
- **THEN** Tool 使用固定模块用例 GraphQL Operation 返回有界用例身份列表

#### Scenario: 按计划查询用例
- **WHEN** 调用包含明确测试计划 UUID 和 limit
- **THEN** Tool 使用固定计划用例 GraphQL Operation 返回有界用例身份列表

#### Scenario: 模块查询缺少测试库
- **WHEN** 调用选择模块模式但未提供测试库 UUID
- **THEN** Tool 在连接 Provider 前返回稳定输入错误

### Requirement: 现有ONES工作项搜索必须保持Schema兼容
现有 `ones_work_item_search` MUST 保持已发布的 `keyword`、`issue_type=demand|task|defect`、`limit` 输入 Schema 和 `number/name/type/total/truncated/untrusted_data` 输出语义。服务端 SHALL 通过真实 ONES 工作项类型与 `group-task-data` 查询实现该兼容 Tool；不得继续依赖仅存在于 Mock 的自定义 Provider 响应，也不得在类型名称或 UUID 歧义时猜测。

#### Scenario: 旧Publication调用工作项搜索
- **WHEN** 旧 Agent/Application Publication 冻结的 `ones_work_item_search` Schema 与当前 Manifest 一致
- **THEN** 新代码按原输入输出契约执行真实 ONES 固定查询
- **AND** 不因本 change 新增 Tool 而自动扩展旧 Publication 的权限

#### Scenario: 稳定类型无法唯一解析
- **WHEN** 当前默认 Team 中 `demand|task|defect` 无法映射为唯一 ONES 工作项类型
- **THEN** Tool 返回稳定配置或 Provider schema 错误且不执行扩大范围的工作项查询

### Requirement: ONES Mock不得复制真实业务抓取
独立 ONES Mock SHALL 使用仓库合成 fixture 精确模拟新增固定 GraphQL/REST 请求、401 refresh、403、非法查询类型、超大响应、非法结构和截断结果。`ones_mock/ones/` 中的真实抓取内容 MUST NOT 被提交、加载为运行时 fixture、写入测试快照或复制到审计。

#### Scenario: Mock返回项目和时间线
- **WHEN** 聚焦测试调用新增项目和时间线 Tool
- **THEN** Mock 使用固定假 UUID、假姓名和假消息返回与 Parser 所需字段一致的响应

#### Scenario: 测试代码引用真实抓取目录
- **WHEN** 架构测试发现生产、Mock 或测试代码在运行时读取 `ones_mock/ones/`
- **THEN** 测试失败并要求使用合成 fixture
