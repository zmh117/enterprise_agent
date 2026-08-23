# 08 当前设计决策

1. MCP 替换工具协议和旧平台抽象，不删除身份、RBAC、范围、Secret、审计和发布治理。
2. 工具目录由代码 Manifest 提供，管理端只读展示；不做动态 Handler/Release。
3. Resource 在平台发布，Application 不做 Resource Mapping。
4. 用户输入会变化，因此 Job 不冻结推断目标；Agent 在实际 Tool Call 中选择，服务端实时复核。
5. Worker 只连接 Python Runtime；历史 TypeScript Runtime 事实只读。
6. ONES 身份事实与加密业务调用凭据分表；`ones-mcp` 只为当前用户解析 ACTIVE
   credential，首次 401 最多刷新一次。
7. File Service 是文件/MinIO 唯一入口；原始文档通过 Docling 生成受治理表示后才进入
   Agent 文件上下文。
8. MCP 不新增第二套管理治理层；现有身份、应用、工具、范围、Secret、发布和审计继续生效。
