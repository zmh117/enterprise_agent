# Python Runtime internal boundaries

Python Runtime 使用静态装配，不提供 Runtime、MCP 或 Provider 插件注册入口。

依赖方向：

```text
service -> executor
executor -> model_binding / mcp_config / tool_policy
executor -> job_sandbox / existing invocation and file boundaries
mcp_config -> claude_client / file_mcp_bridge / tool_policy
claude_client -> sdk_event_normalizer / error_mapper
sdk_event_normalizer -> error_mapper
```

- `executor.py` 拥有单次 attempt 编排和确定性验收 provider。
- `claude_client.py` 只封装 Claude Agent SDK/CLI 调用、模型临时环境和 SDK stream。
- `mcp_config.py` 只构造部署固定的 Tool、ONES 与 File MCP 会话并维护 File bridge 生命周期。
- `tool_policy.py` 维护精确 Tool allow/deny、禁止输入字段和 Runtime tool event 分类。
- `sdk_event_normalizer.py` 与 `error_mapper.py` 只处理有界事件、计量、错误分类和脱敏。

模块之间不得导入以下划线开头的符号，不得形成循环依赖，也不得增加动态 client/Server registry、插件扫描、任意 Runtime/MCP URL 或通用执行入口。
