## ADDED Requirements

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
