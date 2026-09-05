## ADDED Requirements

### Requirement: Agent Job 本轮文件准入必须形成单一不可变决策
系统 MUST 在创建或补建 Task Workspace、持久化 Agent Job 或系统通知、冻结 Job File Manifest 之前，根据当前消息文字、ingress 输出意图 hint、当前消息附件、显式 File/Version 引用、引用消息、冻结的 Business Application Publication 文件策略、当前活动工作区候选和仍有效的跨会话保留候选，形成单一不可变的本轮文件准入决策。该决策 MUST 同时冻结有效输出意图、文件能力依赖及其绑定原因、Gate action 与安全原因码、Task Workspace 需求、Manifest Working Set 与自动物化计划，以及等待附件完成后重新评估所需的安全事实；后续调用方 MUST 消费该决策，不得重新解析消息或根据 `TIME_WINDOW`、能力类型、候选数量等内部字段推导另一套准入结果。

#### Scenario: 输出请求中的时间词不触发历史附件绑定
- **WHEN** 用户请求“生成 md 文件记录我今天的对话”且没有当前消息附件或显式文件来源
- **THEN** 单一准入决策把该消息识别为文件输出请求并返回 `enqueue_job` 与 `no_file_dependency`
- **AND** 系统不得把“今天”重新解释为历史工作区文件时间窗口

#### Scenario: 输出请求显式指定时间窗口文件来源
- **WHEN** 用户请求“根据今天上传的文件生成汇总.md”且存在仍可访问的时间窗口候选
- **THEN** 单一准入决策返回最多 20 个 `METADATA + TIME_WINDOW` 候选
- **AND** Task Workspace 与 Job File Manifest 消费该决策时不得把候选正文自动物化

#### Scenario: 准入结果统一驱动工作区与 Manifest
- **WHEN** 本轮准入决策要求创建或复用 Task Workspace 并允许创建 Agent Job
- **THEN** Workspace 解析、File MCP Tool Snapshot 启用判断与 Job File Manifest binding plan MUST 消费同一准入决策
- **AND** Agent Job 创建 implementation 不得再次检查绑定原因、能力类型或候选数量来改变 Workspace 或自动物化结果

#### Scenario: 安全通知复用同一准入结果
- **WHEN** 准入决策因非法日期、空时间窗口、候选超限、绑定歧义或文件能力不可用而返回 `system_notice`
- **THEN** 系统 MUST 使用该决策冻结的原因码和安全事实生成既有中文通知且不创建 Agent Job
- **AND** 通知路径不得重新解析原始消息或重新选择文件候选

### Requirement: 等待中的文件准入必须从冻结事实恢复
因当前消息附件来源或可读内容尚未就绪而创建的等待中 Agent Job MUST 持久化与初始准入决策兼容的安全依赖事实。附件状态变化后，系统 MUST 仅使用冻结依赖身份和刷新后的来源、可读性状态重新评估 Gate，不得重新解析原始消息、重新运行输出意图识别或纳入决策冻结后出现的新候选；现有 `file_turn_dependencies` payload MUST 保持向后兼容，使变更部署前创建的等待中 Job 可以继续恢复。

#### Scenario: 当前消息附件处理完成后恢复
- **WHEN** 等待中 Agent Job 的当前消息附件完成导入或可读内容生成
- **THEN** 系统以冻结依赖身份和刷新后的状态重新评估原 Gate，并按既有规则释放 Job 或发送安全通知
- **AND** 系统不得因工作区新增文件或消息文字重新解析而改变本轮绑定集合

#### Scenario: 部署前创建的等待中 Job 恢复
- **WHEN** 新 implementation 读取变更部署前持久化的 `file_turn_dependencies`
- **THEN** 系统 MUST 无需数据迁移即可恢复等价的文件依赖并完成 Gate 重新评估
- **AND** 不得因缺少新内部类型或字段而拒绝、扩展或猜测依赖

### Requirement: 文件准入重构必须保持既有受治理行为
文件准入 module 的深化 MUST 保持 canonical 文件绑定优先级、确定性绑定范围、时间窗口上限、用户可见中文通知、Agent Job 与纯系统通知分流、Task Workspace 生命周期、Job File Manifest schema v5、物化时授权复检和 File Service 权威不变。系统 MUST 继续把模型判断限制在冻结的有界元数据候选之后，不得把自然语言分类或准入决策解释为长期文件授权。

#### Scenario: 当前附件与精确引用保持优先
- **WHEN** 当前消息附件或显式 File/Version 引用与指示语、时间窗口候选同时存在
- **THEN** 深化后的准入 module MUST 保持 canonical 优先级并形成与变更前等价的确定性绑定

#### Scenario: Manifest 冻结后授权失效
- **WHEN** 准入决策已经形成且 Job File Manifest 已冻结，但用户或应用在物化前失去文件访问权
- **THEN** File Service MUST 继续在物化时拒绝访问
- **AND** 准入决策不得被解释为长期授权
