## ADDED Requirements

### Requirement: Docling处理使用两个数据库协调的全局槽位
`docling-layout-ocr-v2` MUST 把全局Docling并发上限和单parent图片并发上限固定为`2`。File Service MUST 在PostgreSQL中维护恰好两个Docling admission槽位；`file-processing-worker`在提交父文档或图片任务前 MUST 通过已认证的File Service内部接口取得一个槽位，并在外部task处于已提交、执行、轮询或待获取结果状态期间保持同一work identity占用。不同Worker实例不得以进程内信号量、RabbitMQ prefetch或Docling本地队列替代该全局上限。

#### Scenario: 十个独立文件同时进入处理队列
- **WHEN** 十个受支持的source Version同时产生可处理消息
- **THEN** Worker分别为每个文件保留独立processing run和独立Docling请求
- **AND** 任一时刻最多只有两个不同work identity持有Docling槽位，其余消息保持可恢复等待

#### Scenario: 两个Worker同时争抢最后一个槽位
- **WHEN** 两个Worker实例并发尝试为不同work identity取得同一个可用槽位
- **THEN** File Service通过单一数据库事务只允许一个work identity成功
- **AND** 未取得槽位的消息不提交Docling、不增加attempt并按有界策略重新等待

#### Scenario: 同一parent的图片并发处理
- **WHEN** 同一parent下至少两张图片已就绪且两个全局槽位均可用
- **THEN** 最多两张图片可以分别取得槽位并并发调用Docling
- **AND** 第三张图片不得绕过全局上限或单parent上限

#### Scenario: Assembly消息被消费
- **WHEN** 最终assembly只读取已持久化的父结果和图片结果且不调用Docling
- **THEN** Assembly继续使用既有原子claim和幂等发布
- **AND** Assembly不得占用Docling admission槽位

### Requirement: 槽位恢复不得扩大并发或破坏幂等
每个槽位 MUST 绑定稳定的`parent run`或`picture item`身份，并将Worker lease与work identity分离。Worker lease过期时，系统 MUST 只允许同一work identity接管并恢复该槽位；只要外部Docling task仍可能存在，槽位不得仅因Worker心跳或lease过期而分配给不同work identity。槽位只能在结果已持久化到受控staging、外部task确定终态且不再需要取回、或Docling重启后已确定task不存在时释放；状态不确定时系统 MUST 失败关闭并报告安全原因码。

#### Scenario: Worker提交Docling后退出
- **WHEN** Worker已持久化外部task ID并占用槽位，但在Docling完成前退出
- **THEN** RabbitMQ重新投递后由同一work identity接管原槽位并继续轮询或恢复
- **AND** 该槽位不得因原Worker lease过期而让第三个work identity提交Docling

#### Scenario: Worker在提交前退出
- **WHEN** Worker取得槽位并提交本地claim，但尚未创建外部task即退出
- **THEN** 同一work identity在lease过期后接管槽位并按原attempt继续
- **AND** 唯一claim与槽位约束阻止重复Docling提交

#### Scenario: 外部task状态无法确定
- **WHEN** 处理deadline已到但Docling仍可能执行或保存该task
- **THEN** 系统隔离该槽位并把能力报告为不可安全继续或降级
- **AND** 系统不得把槽位直接分配给其它work identity后宣称并发仍为`2`

#### Scenario: 结果持久化后重复收到消息
- **WHEN** Docling结果已经进入受控staging或对应work已经终态，但相同消息再次到达
- **THEN** 原子claim和唯一约束复用既有状态并安全确认消息
- **AND** 不重复提交Docling、不重复释放槽位、不发布重复Representation
