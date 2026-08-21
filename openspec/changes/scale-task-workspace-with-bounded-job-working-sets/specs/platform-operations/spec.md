## ADDED Requirements

### Requirement: 工作区文件数量与计费容量使用受治理tenant运行配置
平台 Runtime Config SHALL注册两个非敏感整数定义：`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`默认200、代码硬上限1000；`FILE_WORKSPACE_BILLABLE_BYTES_LIMIT`默认2GiB、代码硬上限10GiB；二者仅适用`file-service`。Runtime Config scope SHALL增加`tenant`，但只有代码显式声明tenant-compatible的定义才可使用；scope code MUST从已认证管理上下文中的平台tenant身份校验，不得由普通业务请求或Agent输入覆盖。

管理员创建、修改、禁用tenant覆盖时 MUST经过现有平台配置管理权限、乐观revision和配置审计。File Service MUST把两个有效值及同一配置快照revision用于事务配额预留；有效配置诊断 MUST返回脱敏的值、来源和revision。Job审计 MUST记录观察到的有效值与revision，但公开健康检查不得暴露tenant目录或文件身份。

#### Scenario: tenant使用默认配额
- **WHEN** 没有启用的tenant覆盖且兼容上线门禁已通过
- **THEN** File Service有效配置返回文件数量上限200和计费容量2GiB及definition-default来源
- **AND** 代码仍分别应用1000和10GiB硬上限

#### Scenario: 管理员设置tenant覆盖
- **WHEN** 授权管理员把目标tenant文件上限从200改为500、容量从2GiB改为5GiB并提供正确expected revision
- **THEN** 平台保存新revision并写入不含文件身份的配置审计
- **AND** 后续File Service有效快照对该tenant使用500和5GiB

#### Scenario: 配额值超过代码硬上限
- **WHEN** 管理员提交1001个ACTIVE文件或超过10GiB的tenant覆盖
- **THEN** 平台在保存前拒绝并返回稳定的定义校验错误
- **AND** File Service消费端仍保留同一硬上限作为纵深防御

#### Scenario: 非兼容定义尝试tenant scope
- **WHEN** 管理员对未声明tenant-compatible的其它Runtime Config key提交tenant scope
- **THEN** 平台在保存前拒绝
- **AND** 不扩大该配置在其它tenant或服务中的作用范围

### Requirement: 提升tenant工作区配额前必须通过兼容预检
平台在把任一tenant有效工作区文件数量从20或更低提升到20以上前，MUST只读检查该tenant所有启用且使用任务工作区的Agent/Application Publication是否冻结兼容的`task_workspace_search_files`及必要File MCP Tool。任一不兼容发布 MUST阻止文件数量提升，并返回有界、非敏感的Application/Publication身份和修复原因；预检 MUST NOT原地修改或自动重发任何Publication。容量覆盖可以独立变更，但两个定义均必须经过同一tenant配置治理、硬上限和审计。

#### Scenario: 所有启用Publication均兼容
- **WHEN** 目标tenant的启用任务工作区Application均冻结兼容Tool且配额值不超过1000
- **THEN** 管理员可发布新的tenant配额revision
- **AND** 审计同时记录预检结果摘要和配置变更

#### Scenario: 存在不兼容历史Publication
- **WHEN** 目标tenant仍有一个启用Application Publication缺少新发现Tool
- **THEN** 平台拒绝把有效上限提升到200
- **AND** 不修改该Publication、现有工作区或历史Job

#### Scenario: 回滚配额到20
- **WHEN** 运维把已启用大工作区的tenant有效上限降回20
- **THEN** 已完成Job、追加工作集事实和已有文件保持不变
- **AND** 超过20个ACTIVE文件的工作区保持可读但拒绝新增逻辑文件

### Requirement: 大工作区上线必须保存容量与全链证据
上线验收 MUST覆盖200和1000个ACTIVE文件、默认2GiB与硬上限10GiB、冻结目录revision的50项分页、40个内容工作集项、64文件分区、224MiB共享容量、并发目录变化、并发Job和Docling Representation状态，并记录目录revision成员行数、Manifest大小、Job创建与搜索延迟、数据库查询计划以及工作集/容量上限拒绝。验收 MUST覆盖自动物化、File MCP物化、Write/Edit和内部临时文件全部经过统一预算，特别证明File MCP不能绕过文件数或容量检查。生产就绪声明 MUST至少包含一次真实Runtime调用File MCP搜索、选择精确版本、物化可读内容并形成Agent结果或Delivery的全链证据；容器健康或单元测试单独不足以证明完成。

#### Scenario: 1000文件容量压测
- **WHEN** 测试工作区具有1000个ACTIVE文件且创建只绑定2个内容项的Job
- **THEN** Manifest只冻结目录revision和2个内容项，不复制其余998个目录条目
- **AND** 证据记录冻结目录分页延迟、查询计划和数据库行数而不记录正文

#### Scenario: 真实全链验收
- **WHEN** 兼容Publication通过真实Python Runtime搜索并选择一份Docling可读文档
- **THEN** 证据证明精确Representation被物化、Agent读取并产生受治理结果或Delivery
- **AND** 未选中的工作区文件没有进入Sandbox

#### Scenario: File MCP预算旁路回归
- **WHEN** Runtime已经接近40项输入或224MiB容量且File MCP返回新的合法transfer
- **THEN** Runtime在下载首字节前通过统一预算接受或稳定拒绝
- **AND** 证据证明拒绝路径没有目标文件、部分内容或未释放预留

## MODIFIED Requirements

### Requirement: Job Sandbox容量和隔离配置必须可验证
Python Runtime临时文件系统配置 MUST对每个Job实施64个常规文件槽位和224MiB共享容量：`inputs`最多40个、`work/outputs`合计最多16个、内部临时及安全余量保留8个。全部自动物化、File MCP按需物化、Agent Write/Edit、输出选择和内部临时处理 MUST经同一个`JobSandbox`预算与预留服务；File MCP不得在授权成功后直接写盘绕过文件数、分区或容量检查。Compose、Runtime默认值、代码硬限制和readiness MUST保持一致，并在健康状态中只显示非敏感上限。

输入计数按实际进入Sandbox的唯一File/Version计算，重复物化同一版本复用既有entry且不重复计数。Office、PDF和图片只允许其精确Markdown Representation进入Sandbox，每个原始File/Version计为一个输入；原始二进制和Docling JSON不得进入Sandbox。64个文件槽位与224MiB是两个同时生效的边界；预留的输出槽位不保证独立字节容量，全部分区仍共享224MiB。

#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime配置不是64文件/224MiB，或无法保留40输入、16工作输出和8个内部余量槽位
- **THEN** Runtime readiness失败而不是在Agent执行中使用漂移的边界

#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过对应分区文件数、64文件总数或224MiB共享容量
- **THEN** Runtime在创建目标文件或写入首字节前拒绝并返回安全、有界错误

#### Scenario: 原始文档被请求物化
- **WHEN** Runtime尝试把PDF、Office、图片或Docling JSON写入Agent Sandbox
- **THEN** 类型门禁在下载字节前拒绝

#### Scenario: 自动物化批次不能完整容纳
- **WHEN** 计划自动物化输入超过40个不同File/Version或实际表示总大小会突破224MiB
- **THEN** Job在创建与outbox前完整失败并要求缩小工作集
- **AND** 不创建半数输入已冻结或已物化的Job

#### Scenario: File MCP物化失败释放预留
- **WHEN** File MCP物化已预留输入槽位和容量但下载失败或SHA-256不匹配
- **THEN** Runtime清理部分文件并释放相同预留
- **AND** 后续重试仍从真实Sandbox使用量重新校验
