## ADDED Requirements

### Requirement: Tool Call响应摘要必须先结构化投影再限制长度
MCP 根 Tool Call 新写入及受授权的管理/Debug 读取 MUST 输出有界元数据摘要，不将集合、文件正文或业务对象复制到时间线。历史 JSON、payload、MCP text 和 runtime_file_bridge 包装 MUST 在有限大小与深度内解析后按固定字段投影；不得先截断 JSON 或在解析失败后直接回显原字符串。不可恢复摘要 MUST 明确标记不可用，传输包装截断不得冒充业务查询截断。

#### Scenario: 大结果的计数字段位于正文之后
- **WHEN** 合法历史响应正文超过2000字符且 returned 等字段位于集合之后
- **THEN** 管理详情返回完整的计数/完整性小对象，不返回任何集合正文

#### Scenario: 历史摘要已损坏
- **WHEN** 历史 JSON 已截断或超过读取预算
- **THEN** 返回摘要不可用标记，不展示原字符串或推测总量

### Requirement: 文件工具时间线必须区分操作阶段
时间线 MUST 根据实际 Tool 名称、调用状态与可用元数据展示文件读取、沙盒写入、提交意图和输出选择。文件正文、认证材料和不透明提交凭证 MUST NOT 展示；提交意图/选择输出 MUST NOT 声称文件已正式提交，不得根据缺失的历史元数据生成大小或路径。

#### Scenario: 沙盒写入成功
- **WHEN** Write 调用成功并有安全内容字节数
- **THEN** 显示沙盒写入完成及字节数，并说明尚未提交

#### Scenario: 创建提交意图或选择输出
- **WHEN** file_create_commit_intent 或 select_sandbox_output 成功
- **THEN** 显示对应阶段，不用通用占位文案，也不声称文件已提交

### Requirement: Worker与Runtime提示词版本必须使用共享事实源
Worker 默认执行上下文与 Python Runtime 工具契约观测 MUST 从共享模块引用同一 Prompt template version。Worker MUST 继续严格验证观测 hash、Job snapshot hash、提示词版本与组件构建身份，不得因版本升级移除校验或静默改写请求版本。

#### Scenario: 默认上下文进入Runtime
- **WHEN** 同一版本组件以默认上下文构造请求并生成真实工具契约观测
- **THEN** 观测通过 Worker 事件校验且可继续接收终态

#### Scenario: 混用不同版本组件
- **WHEN** 观测提示词版本与请求不一致
- **THEN** Worker 以 runtime_protocol_error 失败关闭，不持久化被拒绝事件为已验证事实

### Requirement: Runtime协议失败必须展示安全字段差异
Runtime 协议失败 MUST 经既有错误步骤及执行摘要返回代码固定的中文拒绝原因。工具契约不匹配 MUST 包含事件序号、字段和安全期望/实际值；只允许固定格式 Prompt 版本及 SHA-256，其他值只显示缺失、不匹配或无效格式，不包含被拒绝事件正文、Prompt、凭据或堆栈。运行记录 MUST 显示已有 failure_summary 与 failure_code，初始化失败不得伪造 Tool Call。

#### Scenario: 提示词版本不匹配
- **WHEN** Worker 请求 v6、Runtime 观测 v5
- **THEN** 失败步骤及运行记录显示 prompt.template_version、两个版本和 runtime_protocol_error

#### Scenario: 字段包含非规范正文
- **WHEN** Runtime 版本字段携带任意业务正文、敏感链接或认证材料
- **THEN** 只显示无效格式或固定校验原因，不回显该值
