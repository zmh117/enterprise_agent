## ADDED Requirements

### Requirement: Job文件工作集选择必须可恢复且不改变Runtime协议
系统 SHALL把Job初始文件Manifest与执行期间追加的精确文件工作集事实分开持久化。初始Manifest继续不可变并按既有schema/hash验证；追加工作集事实 MUST使用Job、Snapshot、精确File/Version和可选Representation身份保持幂等，并在Worker重试、Runtime断线恢复和相同invocation恢复时复用，MUST NOT重新选择“当前最新”版本或产生第二套内容授权。

追加工作集事实属于控制面与File Service授权事实，MUST NOT新增或改写Runtime 1.2/1.3请求、事件或终态字段。Runtime只通过已经冻结的File MCP Tool、短时Principal和受控transfer取得动态选择内容，仍不得接收MinIO凭据、对象位置或原始二进制。

#### Scenario: Runtime断线后恢复同一Job
- **WHEN** Job已经追加选择V3及Representation R1并创建受控transfer，Worker在Runtime终态前断线
- **THEN** 恢复继续使用相同Job工作集事实和精确V3/R1
- **AND** 不重新解析当前V4或Representation R2

#### Scenario: 并发重复选择同一版本
- **WHEN** 同一Job并发两次选择相同File/Version
- **THEN** 唯一约束和事务只保留一个追加工作集事实
- **AND** 两次调用得到一致身份且工作集计数只增加一次

#### Scenario: Runtime合同仍使用受支持版本
- **WHEN** 兼容大工作区Job执行搜索、动态选择和物化
- **THEN** Worker与Python Runtime仍使用已发布的Runtime 1.2或1.3合同
- **AND** Runtime schema校验不要求新的文件工作集字段

#### Scenario: Job重试时权限已经撤销
- **WHEN** 追加工作集事实仍存在但当前用户或Application访问在重试前被撤销
- **THEN** File Service在再次物化前失败关闭
- **AND** 不把追加事实解释为长期访问授权
