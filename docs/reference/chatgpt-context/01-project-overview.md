# 01 项目概览

平台面向企业内部受治理诊断：从钉钉、Webhook 或 Debug API 创建 Job，经 Worker 调用
唯一 Python Runtime。模型可通过固定 `tool-mcp` 查询 DB/Redis/Loki，通过
`ones-mcp` 使用当前用户 ONES 身份查询，通过 File MCP 操作受治理任务文件；结果按
Application Publication 的交付配置返回。

核心能力：

- 统一用户、钉钉/ONES 外部身份、RBAC 与审计；
- Agent/Application 追加式 Revision 与不可变 Publication；
- 独立的 Python Agent Runtime；历史 TypeScript Runtime 事实仅供只读审计；
- 标准 MCP Tool Manifest、Agent/Application Envelope 与 Job Snapshot；
- ONES 本人绑定、加密个人凭据和两个固定只读 ONES Tool；
- File Service、Task Workspace、Manifest v5、Docling Representation 与精确版本交付；
- 数据库、Redis、Loki 资源和 Secret Ref；
- Job、Session、Tool Call、Artifact、Delivery、Runtime Event 历史。

明确不做：任意 URL/脚本/Shell、动态 MCP Server、旧 API Platform 抽象、第二套 MCP
专用治理层或 Application Resource Mapping。文件写入只发生在受治理 Sandbox/File MCP
边界，不是通用主机写能力。
