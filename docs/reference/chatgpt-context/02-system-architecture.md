# 02 系统架构

```text
Admin Web --------------------> API Control Plane
DingTalk/Webhook/Debug --------> Ingress + Outbox/Dispatch
                                      |
                              PostgreSQL/RabbitMQ
                                      |
                                  Agent Worker
                                      |
                             Python Agent Runtime
                          /            |             \
                    tool-mcp        ones-mcp       File MCP
                       |               |              |
               Published Resource  User credential  File Service
                                                    /          \
                                             MinIO       Docling pipeline
```

Worker 不内嵌 Claude SDK，也不执行工具；它只调用 `python-v1` Runtime。历史
`typescript-v1` 事实只读且不可创建新 Job。Runtime 只连接 Publication/Job 冻结的固定
MCP Server 和 Tool。

Control Plane 保存身份、角色、配置、发布、资源、Secret metadata、Job/File provenance
和审计。DB/Redis/Loki 访问发生在 `tool-mcp`；ONES Provider 访问发生在 `ones-mcp`；
MinIO 访问只发生在 File Service。
