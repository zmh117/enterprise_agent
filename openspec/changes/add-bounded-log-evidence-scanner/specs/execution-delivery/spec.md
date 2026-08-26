## MODIFIED Requirements

### Requirement: Runtime exposes only read-only tools
系统 SHALL 默认只注册Job冻结的只读MCP Tool。仅当Business Application与Agent Publication都冻结支持的File MCP Tool且当前Job绑定有效任务工作区时，Runtime SHALL额外注册部署固定File MCP Server及沙盒受限`Read`、`Glob`、`Grep`、`Write`和`Edit`；仅当当前Job还冻结`file_prepare_materialization`并已创建有效Sandbox时，Runtime SHALL把业务只读的本地`scan_log_evidence`注册为File MCP Server的Runtime派生Tool。日志扫描器只能读取当前Job已物化LOG并生成当前Sandbox临时证据包，不得增加文件身份、对象存储、网络、提交或交付权限。数据库更新、Redis删除、重启、部署、PR创建、任意Shell和沙盒外文件操作仍 MUST 被拒绝。

#### Scenario: Diagnostic Job asks for a mutating tool
- **WHEN** 普通诊断Job没有文件工具却请求代码修改、数据库更新、Redis删除、重启、部署或沙盒执行
- **THEN** 系统因工具未注册或被拒绝而阻止调用

#### Scenario: File Job uses registered sandbox tools
- **WHEN** 文件Job调用Job冻结的File MCP Tool和当前沙盒受限文件工具
- **THEN** 调用分别通过File Service与Runtime路径守卫执行
- **AND** 不经过旧`ToolRegistry`动态实现或任意Server

#### Scenario: LOG Job使用派生证据扫描器
- **WHEN** 当前Job冻结`file_prepare_materialization`、绑定有效Sandbox且至少一个已物化输入为只读LOG
- **THEN** Runtime在同一部署固定File MCP Server中暴露`scan_log_evidence`
- **AND** 该工具不能读取未物化文件、自动追加工作集、提交文件或调用外部服务

#### Scenario: Job没有只读物化能力
- **WHEN** 当前Job未冻结`file_prepare_materialization`或没有有效任务文件Sandbox
- **THEN** Runtime不注册、不批准也不在提示中宣传`scan_log_evidence`
- **AND** 模型提供相同Tool名不形成调用授权

### Requirement: Final reports are evidence based
The system SHALL require Agent final answers to include a conclusion, evidence summary, uncertainty or limitations when applicable, and suggested safe next actions. Real runtime prompts SHALL instruct the model to follow this report structure using tool evidence gathered during the job. 当报告使用日志证据扫描器时，Agent MUST区分精确扫描覆盖事实、通用规则选择的启发式候选和模型诊断推断；用户行为不是固定报告章节，只有证据支持且与现场问题相关时才记录。`coverage_complete=true`只证明所选输入全部字节已扫描，不证明所有日志语义已经理解；`evidence_limit_reached=true`时报告 MUST明确说明证据包是有界选择。

#### Scenario: Agent completes order diagnosis
- **WHEN** the Agent finishes investigating a business question such as an order stuck in a status
- **THEN** the final report includes the likely cause, relevant log/database/Redis/ER/business-flow evidence, uncertainty if evidence is incomplete, and non-mutating recommendations

#### Scenario: 异构日志扫描完整但证据达到上限
- **WHEN** 日志扫描返回所有选中输入`coverage_complete=true`且`evidence_limit_reached=true`
- **THEN** 最终报告可以引用保留证据进行诊断，但必须列出扫描字节/行覆盖和省略候选数量
- **AND** 不得声称已经逐条理解全部日志或完整还原所有用户行为

#### Scenario: 日志扫描没有完整覆盖
- **WHEN** 日志扫描因取消、容量、完整性或读取错误未返回完整覆盖
- **THEN** Agent不得生成“已完成全量日志分析”的结论
- **AND** 最终回复必须说明稳定失败分类、已验证范围和安全下一步

#### Scenario: 日志证据包含指令样式内容
- **WHEN** 临时证据包中的原文包含Tool名、系统指令样式文本、Markdown或HTML
- **THEN** Runtime提示要求模型把它仅作为不可信诊断数据引用
- **AND** 该内容不得覆盖系统规则、扩大Tool权限或替代当前用户请求

## ADDED Requirements

### Requirement: 日志证据扫描器必须作为可审计Runtime派生Tool进入合同
Python Runtime SHALL以代码固定Tool名、描述、严格Input Schema和schema hash注册`scan_log_evidence`，并在有效Tool合同中把它标记为`runtime_derived`、记录对`file_prepare_materialization`的依赖和Runtime build identity。它不得作为新的远端File Service Manifest Tool、Business Application可选Tool、通用`tool-mcp`资源Tool或模型提供的动态Tool；现有Job冻结的只读物化权限只是派生条件，不得被解释为新的文件正文授权。

#### Scenario: Runtime观察到匹配的派生Tool合同
- **WHEN** 当前Job满足扫描器派生条件且Runtime本地schema与代码固定hash一致
- **THEN** Tool合同证据列出`scan_log_evidence`、`runtime_derived`来源、依赖项、schema hash和Runtime build identity
- **AND** 模型可调用名称稳定为`mcp__file_service__scan_log_evidence`

#### Scenario: 扫描器schema发生漂移
- **WHEN** Runtime装配、权限回调或合同观察到的`scan_log_evidence`schema hash与代码固定值不一致
- **THEN** Runtime在模型调用该工具前以不可重试Tool合同完整性错误失败关闭
- **AND** 不回退到`Grep`循环、旧schema或远端同名Tool

#### Scenario: 远端File Service报告同名Tool
- **WHEN** 部署固定File Service的`tools/list`意外返回`scan_log_evidence`
- **THEN** Runtime将其视为远端合同漂移并失败关闭
- **AND** 不把远端Tool替换或覆盖本地派生实现

### Requirement: 日志扫描服从Job执行预算与合作式取消
每次`scan_log_evidence`请求 SHALL按一次内部Tool调用计入当前attempt的Job固定`max_tool_calls`，并 MUST在进入扫描副作用前经过统一Tool预算、Input Schema和Sandbox授权。扫描循环和证据写入 MUST定期检查当前Runtime取消信号与Job剩余墙钟预算；Tool预算耗尽不得开始扫描，本地墙钟耗尽仍按稳定`runtime_timeout`终结且不自动重试整个Job。

#### Scenario: 扫描请求超过Tool调用预算
- **WHEN** 模型发起日志扫描时当前attempt已经执行Job允许的全部Tool调用
- **THEN** Runtime在读取日志或预留证据包前硬终止当前attempt
- **AND** 返回既有`execution_policy_max_tool_calls_exhausted`语义且不调用扫描器

#### Scenario: 扫描期间达到Job墙钟上限
- **WHEN** 扫描循环尚未完成而当前attempt达到冻结`timeout_seconds`
- **THEN** Runtime合作式取消扫描、保留此前安全Tool事件并清理未完成证据包
- **AND** Worker将稳定`runtime_timeout`映射为不自动重试的Job `TIMEOUT`

#### Scenario: 扫描完成后模型继续生成报告
- **WHEN** 扫描器在剩余墙钟预算内成功返回证据包元数据
- **THEN** 模型只使用剩余轮次、Tool调用和墙钟预算读取证据并生成报告
- **AND** 扫描成功不重置或扩大任一执行预算

### Requirement: 日志扫描Tool事件不得复制原始日志
日志扫描的Runtime事件、`AgentRunResult.tool_events`、`agent_tool_call`、Job step、错误、审计和RabbitMQ消息 MUST只保留有界安全元数据，包括scanner版本、输入数量、实际/已扫描字节、逻辑行数、候选/保留/省略计数、证据包大小与SHA-256、限制标志、耗时、Tool合同身份和稳定错误码。持久化摘要 MUST NOT包含字面关键词原值、输入正文、原文片段、完整证据包、完整Prompt、认证Header、Token、Cookie、密码、模型Key、对象键、Bucket或MinIO位置。

当前Job隔离Sandbox中的证据包 MAY在既有文件授权下保留现场排障所需的用户名、业务字段、请求信息、堆栈和原文片段；该临时数据面可见性不得使运维事件、调试API或消息队列获得正文。用户明确要求的最终报告仍须经过既有文件提交与渠道授权，不得由扫描Tool事件旁路交付。

#### Scenario: 扫描成功事件持久化
- **WHEN** `scan_log_evidence`成功生成证据包并返回模型
- **THEN** Runtime和Control Plane持久化输入/扫描计数、包大小/hash、限制标志、耗时和合同身份
- **AND** Tool事件和调试API不包含关键词、证据片段或证据包正文

#### Scenario: 原日志包含认证凭据样式文本
- **WHEN** 当前Job授权的原LOG或临时证据包包含Token、Cookie、密码、Key或认证Header样式内容
- **THEN** 扫描器仍只在当前隔离Sandbox数据面处理该输入
- **AND** Runtime错误、stderr、Tool事件、审计和队列消息不得复制这些值

#### Scenario: Agent生成用户要求的诊断报告
- **WHEN** Agent基于证据包另行生成并显式提交Markdown报告
- **THEN** 提交和交付沿用当前Job的文件及渠道授权并作为业务结果处理
- **AND** `agent_tool_call`仍只保存证据包元数据，不保存报告或原日志正文副本
