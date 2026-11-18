## ADDED Requirements

### Requirement: 源码回答结束前必须有界补足保存机会
Runtime SHALL 对已取得源码读取授权但未成功保存结果的任务，在原预算允许时最多执行一次结束纠正，要求同一 Agent 调用受控保存工具。不得延长截止、突破工具或模型轮次上限、创建另一任务或将普通回答直接转为确定知识。补保存失败 MUST 保留业务回答和独立失败事实；partial/conflicted 仍不得索引。

#### Scenario: 未调用保存就结束回答
- **WHEN** 已取得源码 grant 的 Agent 首次准备结束，尚无成功保存且预算允许
- **THEN** 原会话收到一次保存纠正；再次结束时不无限阻止

#### Scenario: 已保存或无需源码
- **WHEN** 已保存 supported/partial/conflicted 结果，或本次只读取已有答案
- **THEN** 正常结束，不增加保存调用或重复向量

#### Scenario: 无法补保存
- **WHEN** 预算耗尽、身份权限失效，或一次纠正仍未成功
- **THEN** 保留已形成的业务回答，后台记录实际保存状态，不声称知识已入库
