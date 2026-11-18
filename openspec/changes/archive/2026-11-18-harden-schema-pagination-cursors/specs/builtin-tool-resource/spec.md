## MODIFIED Requirements

### Requirement: Schema 分页必须区分下一张表和字段截断
`get_schema_directory` SHALL 默认且最多每页 50 张完整表摘要，使用有界 keyset 表名查询，不为一页无界读取全部字段。cursor MUST 绑定 Job、Tool、精确目标、placement、query 与实际 Resource Revision；每页重新授权并唯一解析。单表字段上限与是否存在下一张表必须独立表达。服务端 SHALL 保存原始游标，在 `next_cursor` 返回当前 Job 的短引用，并在续页时精确恢复后执行原有完整校验；不得让模型解码重建原始游标，不得模糊纠错或跳过校验。临时状态 MUST 有界、限时、可跨实例读取，不包含认证材料。

#### Scenario: 翻过 50 张表
- **WHEN** 允许目录有 51 张匹配表
- **THEN** 首页返回 50 张与短 next_cursor，续页返回第 51 张；Oracle 首页允许空 after_table 下界

#### Scenario: Resource 版本改变
- **WHEN** 续页时唯一解析到的当前 Revision 与 cursor 不同
- **THEN** 返回 stale，不回退旧 Revision

#### Scenario: 只有字段被截断
- **WHEN** 最后一张表字段超过单表上限且没有后续表
- **THEN** 标记字段摘要受限、has_more=false，不生成不存在的表页 cursor

#### Scenario: 换实例继续分页
- **WHEN** 同一运行中 Job 在另一服务实例使用短引用及原查询条件
- **THEN** 服务端恢复原始游标并重新授权、校验目标与修订后续页，无需重建内存状态

#### Scenario: 错误引用或上下文
- **WHEN** 引用损坏、不存在、已过期、来自其他 Job，或请求目标、query、授权上下文变化
- **THEN** 明确拒绝，不猜测原值、不静默从第一页开始、不因持有引用而放宽权限

#### Scenario: 已签发旧游标
- **WHEN** 同一有效 Job 使用旧版本签发的完整长游标
- **THEN** 继续执行原有完整校验；若仍有下一页，则新响应返回短引用

#### Scenario: 存储与生命周期
- **WHEN** 状态存储不可用或 Job 已结束
- **THEN** 不签发可用分页成功结果；过期状态由服务定期有界清理，删除 Job 时级联清理，不保存业务记录正文
