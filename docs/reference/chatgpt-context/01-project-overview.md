# 01 项目概览

平台面向企业内部只读诊断：从钉钉、Webhook 或 Debug API 创建 Job，经 Worker 选择 Python/TypeScript Runtime，模型通过固定 `tool-mcp` 调用只读工具，最终持久化结果并按应用交付配置返回。

核心能力：

- 统一用户、钉钉/ONES 外部身份、RBAC 与审计；
- Agent/Application 追加式 Revision 与不可变 Publication；
- Python 和 TypeScript 两个独立 Runtime；
- 标准 MCP Tool Manifest、发布 Envelope 与 Job Snapshot；
- 数据库、Redis、Loki 资源和 Secret Ref；
- Job、Session、Tool Call、Artifact、Delivery、Runtime Event 历史。

明确不做：任意 URL/脚本/Shell/写操作工具、动态 MCP Server、旧 API Platform 抽象、MCP 专用 Token/RBAC/Resource Mapping。
