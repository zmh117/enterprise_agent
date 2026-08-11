# 02 系统架构

```text
Admin Web --------------------> API Control Plane
DingTalk/Webhook/Debug --------> Ingress + Dispatch
                                      |
                              PostgreSQL/RabbitMQ
                                      |
                                  Agent Worker
                              /                     \
                    Python Agent Runtime   TypeScript Agent Runtime
                              \                     /
                                   tool-mcp
                                      |
                         Published Resource + Secret
```

Worker 不内嵌 Claude SDK，也不执行工具；它根据 Agent Publication 的 `runtime_kind` 调用对应 Runtime。两个 Runtime 都只接收固定 `tool-mcp` 工具描述。`tool-mcp` 负责 Job 快照、实时授权、资源唯一解析和有界只读执行。

Control Plane 保存身份、角色、配置、发布、资源、Secret metadata 和审计；工具数据访问只发生在 `tool-mcp` 的适配器边界。
