## ADDED Requirements

### Requirement: 机器文件时间必须保持 UTC canonical 表达
Job File Manifest、File MCP 响应和 Runtime 文件上下文中的 `source_received_at`、`version_created_at`、`representation_created_at`、`observed_at` 与非空 `expires_at` MUST 输出为带时区的 UTC RFC 3339，并 MUST 表示与持久化事实相同的 instant。Asia/Shanghai 只可用于自然周期计算或展示层本地化，MUST NOT 写入机器协议、不可变快照或 hash 输入。

#### Scenario: UTC 来源时间进入 Runtime
- **WHEN** 持久化来源接收时间为 `2026-08-19T04:49:29+00:00`
- **THEN** Manifest、File MCP 和 Runtime 文件上下文均返回等价 UTC RFC 3339
- **AND** 不把该值改写成 `2026-08-19T12:49:29+08:00`

#### Scenario: Manifest consumer 复算 hash
- **WHEN** Runtime 对 schema 支持的 Manifest 使用返回的 canonical 时间字段复算 hash
- **THEN** 复算结果与冻结的 `manifest_hash` 一致
- **AND** 响应序列化不得在 hash 校验后改变时间 canonical 表达

### Requirement: 显式非法文件日期必须 fail closed
文件上下文解析 MUST 区分没有日期表达、合法日期表达和显式非法日期表达。非法日历日期、非法区间端点或结束早于开始的区间 MUST NOT 回退为今天、最近日期或其它猜测范围；当消息同时具有文件语义时，系统 MUST 返回不创建 Agent Job 的安全澄清。

#### Scenario: 用户输入不存在的日期
- **WHEN** 用户请求“2月30日的文件”
- **THEN** 系统返回日期无效的澄清通知且不创建 Agent Job
- **AND** 不查询、选择或绑定今天的文件

#### Scenario: 普通消息包含非法日期但没有文件语义
- **WHEN** 用户讨论“2月30日这个说法”且没有文件、附件或文档语义
- **THEN** 系统不得据此创建文件时间窗口
- **AND** 普通文字消息路径保持不变

### Requirement: 文件发现候选不得等同于正文绑定
系统 MUST 只对当前消息附件、显式 File/Version ID、引用消息以及消息中出现的完整文件名建立执行前文件能力依赖。时间窗口匹配 MUST 只返回最多 20 个不含正文、凭据和对象位置的 `METADATA` 候选，即使窗口内只有一个文件也不得由 Runtime 预物化正文。部分或近似文件名 MUST NOT 直接形成正文依赖；Agent 选择候选后 MUST 使用精确 File/Version ID 进入受治理物化流程。

#### Scenario: 时间窗口只有一个正文候选
- **WHEN** 用户请求读取上周文件内容且窗口内只有一个仍可访问文件
- **THEN** Job 文件上下文只携带该文件的 `METADATA + TIME_WINDOW` 候选
- **AND** Runtime 不在模型判断前自动物化正文

#### Scenario: 时间窗口候选超过上限
- **WHEN** 合法时间窗口内有超过 20 个仍可访问文件
- **THEN** 系统返回缩小范围的安全通知
- **AND** 不创建携带超限候选或正文的 Agent Job

#### Scenario: 消息只出现部分文件名
- **WHEN** 工作区存在 `production-diagnosis.docx` 而用户只写“diagnosis 文件”
- **THEN** 系统不得把该部分匹配直接绑定为正文依赖
- **AND** Agent 只能从有界元数据中选择精确 File/Version ID

### Requirement: 跨会话保留候选必须在查询时仍有效
跨会话历史附件候选 MUST 在每次查询时同时校验附件可用终态、附件 `expires_at`、binding `retention_expires_at`、文件状态、版本状态以及至少一条未过期的 `file_retention_fact`。缺少或过期的保留事实 MUST fail closed；Cleanup Worker 延迟 MUST NOT 延长候选可见性或正文访问期。

#### Scenario: 保留事实已过期但清理尚未执行
- **WHEN** 文件和对象仍标记为可用，但当前时间已不早于保留事实或 binding 的到期时间
- **THEN** 历史候选查询不返回该 File/Version
- **AND** 不因 Cleanup Worker 延迟允许 Agent 发现或读取正文

#### Scenario: 历史版本没有保留事实
- **WHEN** 旧附件存在 File/Version binding 但没有可验证的有效保留事实
- **THEN** 历史候选查询不返回该版本
- **AND** 系统不补造保留事实或假定无限期有效

#### Scenario: 附件生命周期不可用
- **WHEN** 附件状态为失败、拒绝、处理中或附件内容已经到期
- **THEN** 历史候选查询不返回其绑定版本

