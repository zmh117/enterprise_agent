## MODIFIED Requirements

### Requirement: 工作项搜索公开输入契约固定
ones_work_item_search Input Schema MUST 只公开 keyword、issue_type 和可选 limit。issue_type MUST 限定 demand、task、defect；limit MUST 为1至1000的整数，默认1000，表示本次收集总量而非单页大小。User、Team、Token、URL、GraphQL 和 cursor MUST NOT 公开。

#### Scenario: 自动读取默认总量
- **WHEN** 已授权模型不提供 limit
- **THEN** 程序按1000条上限自动读取，且不要求模型搬运游标

#### Scenario: 非法参数
- **WHEN** 输入 limit 为0、1001、非整数或携带 cursor
- **THEN** 系统在 Provider 调用前拒绝

### Requirement: 工作项搜索公开输出契约固定
ONES 服务 MUST 只返回通过固定类型和大小校验的工作项摘要，每项包含 number、name、type，总量不超过请求上限；输出包含 total、returned、cumulative_returned、truncated、pagination_limit_reached 和 untrusted_data=true。Runtime MUST 将集合内容物化为受控临时结果文件，模型只接收元数据和读取提示。中途失败 MUST 返回安全错误，不得把部分集合发布为成功结果。

#### Scenario: 输出缺少必填字段
- **WHEN** Provider 项无法产生合法 number
- **THEN** 整次调用失败，且不返回部分成功文件

## ADDED Requirements

### Requirement: 删除ONES模拟服务不得改变其他运行配置
仓库 MUST NOT 提供可部署的 ONES Mock 服务；离线测试替身 MUST 仅存在于测试目录，不被生产代码导入、不监听网络。删除 Mock MUST 保留现场文档、原独立 Compose 中其他数据库/Redis测试服务及数据卷；MUST NOT 顺带改变环境示例、连接配置、非 Mock 服务启动/健康校验、项目名称或脚本入口。ones-mcp MUST 保持原方式运行。无真实 ONES 的本地验收 MUST 明确跳过 ONES 链路，不注入模拟身份，不声称真实 ONES 验收通过。

#### Scenario: 只删除Mock服务
- **WHEN** 用户删除本地 ONES Mock，同时要求保留接口修复
- **THEN** Mock 服务及部署入口被移除，ones-mcp 和其他环境配置保持不变，接口修复及离线回归保留

### Requirement: ONES响应必须按接口单位规范化并提供安全字段诊断
Provider Operation MUST 按固定接口的响应结构和单位进行转换。迭代 progress MUST 先将 100000 倍定点值转换为 0..100 百分比并保留有效小数；接口声明为秒、毫秒或微秒的时间 MUST 使用相应明确单位。GraphQL 顶层存在非空 errors 时 MUST 失败关闭，不将部分数据当作完整成功。共享字段校验产生的安全错误 MUST 指明代码拥有的字段路径、期望约束和实际形状，MUST NOT 包含字段原值、认证材料或原始上游错误消息。

#### Scenario: 迭代返回定点进度
- **WHEN** Provider 返回 progress 为 10000000
- **THEN** 工具输出 progress 为 100，不因原值大于100而误判 schema 错误

#### Scenario: 字段类型不匹配
- **WHEN** 某一工作项必填状态或标识字段不符合固定契约
- **THEN** 整次调用失败，安全 error 包含字段路径和类型约束，并经现有审计进入 Tool Call 时间线

#### Scenario: 上游查询错误与部分数据同时返回
- **WHEN** GraphQL 返回非空 errors 与部分 data
- **THEN** 工具返回安全 GraphQL 错误，不发布成功结果文件

### Requirement: ONES自动分页必须遵循官方bucket合同
所有受支持 bucket 列表 MUST 固定 groupBy 为该列表、不做业务分组，保持筛选与排序不变，使用 pagination.limit（最多200）和上页 endCursor 作为 after。终止由 hasNextPage 判断，MUST NOT 依赖 totalCount 推断精确授权总量。不得在本地裁剪 Provider 页后仍使用其页尾游标。直接无 cursor 的完整列表 MUST 单次读取并有界截取，不伪造 Provider 分页。

#### Scenario: 原样续页
- **WHEN** 前页 hasNextPage=true 且尚有额度
- **THEN** 程序原样回传 endCursor，不交给模型，不持久化为续页状态

#### Scenario: 分页不稳定
- **WHEN** unstable=true、出现重复记录或游标、空续页、多 bucket 或返回页超出请求大小
- **THEN** 查询返回对应安全错误，不报告结果完整

#### Scenario: 收集预算耗尽
- **WHEN** 达到50次请求、90秒收集预算或8MiB规范化结果上限
- **THEN** 查询有界终止并返回安全错误；不得无限翻页或扩大授权
