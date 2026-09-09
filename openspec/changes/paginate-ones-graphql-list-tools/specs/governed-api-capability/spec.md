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
