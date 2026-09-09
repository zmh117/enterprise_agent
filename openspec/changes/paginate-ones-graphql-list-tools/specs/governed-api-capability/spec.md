## ADDED Requirements

### Requirement: ONES GraphQL原生分页必须使用代码固定的Provider cursor
对通过 `buckets.pageInfo` 提供 continuation 的 ONES GraphQL 列表 Operation，系统 MUST 将当前页 `endCursor` 封装为平台不透明 cursor，并且只把下一次调用经平台校验后解码的 Provider cursor 注入固定 `$pagination.after`。实际 `$pagination.limit` MUST 不超过当前 Tool 的公开单页上限和分页链剩余额度。模型、Agent、Application 和配置 MUST NOT 直接提供或读取原始 Provider cursor。

#### Scenario: Provider列表正常续页
- **WHEN** Provider 返回 `hasNextPage=true`、合法 `endCursor` 且累计返回数小于 500
- **THEN** 系统签发平台 `next_cursor`
- **AND** 合法续页只把内部解码的 `endCursor` 注入同一固定 Operation 的 `$pagination.after`

#### Scenario: Provider报告后续但缺少游标
- **WHEN** Provider 返回 `hasNextPage=true` 却没有合法 `endCursor`，或返回空页却仍报告存在后续
- **THEN** 整次调用按 Provider schema 错误失败关闭
- **AND** 系统不返回无法继续的部分成功结果

#### Scenario: Provider终页使用累计位置判定
- **WHEN** 续页响应的 `totalCount` 大于当前页 `count` 但 `hasNextPage=false`
- **THEN** 系统结合此前累计返回数判定终页并返回 `truncated=false`
- **AND** 不因只比较总数与当前页数量而重复签发游标

### Requirement: 无Provider cursor的GraphQL直接列表必须使用集合绑定偏移续页
对工作项类型和测试模块等返回完整直接列表但不提供 Provider continuation 的固定 GraphQL Operation，系统 SHALL 在服务端按公开 limit 切片，并将下一偏移、此前累计返回数和完整有序 UUID 集合摘要封装为平台 cursor。续页 MUST 重新执行同一固定查询并验证集合摘要一致；系统 MUST NOT 把本地 offset 或集合摘要直接公开。

#### Scenario: 直接列表合法续页
- **WHEN** 首次完整响应超过公开 limit 且响应仍在 Provider 字节上限内
- **THEN** 系统返回首个本地切片和平台 `next_cursor`
- **AND** 使用该 cursor 的下一次调用从保存的偏移继续返回同一集合

#### Scenario: 直接列表分页期间发生变化
- **WHEN** 续页重新查询得到的有序 UUID 集合摘要与 cursor 保存值不同
- **THEN** 系统返回分页状态已失效并要求从第一页重查
- **AND** 不返回可能重复或遗漏的续页数据

### Requirement: ONES GraphQL列表游标必须绑定当前执行事实
系统 MUST 将每个 ONES GraphQL 列表 `next_cursor` 绑定到精确 Tool identifier、当前 Job、当前用户、业务应用、Agent/Application Publication、授权 hash、Tool input schema、ONES 外部身份、默认 Team 以及不含 cursor 的全部规范化查询参数。系统 MUST 在 Provider 调用前拒绝篡改、跨 Tool、跨 Job、跨用户、跨应用、跨授权、跨 schema、跨身份、跨 Team 或跨查询条件复用的游标。

#### Scenario: 游标跨查询条件复用
- **WHEN** Agent 修改 keyword、项目、迭代、筛选条件或 limit 后复用旧游标
- **THEN** 系统返回分页游标无效且不访问 ONES

#### Scenario: 游标跨Tool或执行主体复用
- **WHEN** 游标被另一个 Tool、Job、用户、业务应用、授权快照、ONES 身份或 Team 使用
- **THEN** 系统返回分页游标无效或已失效且不访问 ONES

#### Scenario: 游标被篡改
- **WHEN** 调用方修改平台 cursor 的任意内容
- **THEN** 系统在解析 Provider cursor、凭据或执行外部请求前拒绝调用
