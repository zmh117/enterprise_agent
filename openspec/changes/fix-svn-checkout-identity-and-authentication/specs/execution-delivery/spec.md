## ADDED Requirements

### Requirement: 源码原生工具拒绝必须保留安全原因
Runtime SHALL 将源码 PreToolUse 中已知的固定拒绝码按 tool use ID 关联到审计事件，输出 DENIED、NEVER 和固定安全提示；未知异常保持通用安全回退。原生文件工具的正文、路径和搜索词 MUST NOT 因此进入普通事件。

#### Scenario: 未取得源码读取授权就调用 Glob
- **WHEN** Hook 因缺失有效 grant 拒绝 Glob
- **THEN** 运行记录显示 CODE_READ_GRANT_REQUIRED 与不可重试分类，不覆盖成 runtime_tool_failed 或 TRANSIENT

#### Scenario: 正常源码读取
- **WHEN** Hook 放行且 SDK 成功完成读取
- **THEN** 保持原有成功事实和证据校验，不伪造失败或重复工具记录
