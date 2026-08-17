# 以 File Service 作为任务文件唯一边界

任务文件采用两层模型：可跨多个 Job 的逻辑 Task Workspace 持久化在 PostgreSQL 和 MinIO；每个 Job 的物理 Sandbox 位于所选 Runtime 容器 tmpfs，并在所有终态清理。File Service 同时承载固定 File MCP 和内部流式 API，是文件身份、版本、配额、生命周期、授权、审计与 MinIO 对象的唯一入口。

第一阶段净新增 `file-service` 容器，以 `file-worker` 替换 `attachment-worker` 并继续消费原附件队列，Delivery Worker 保持独立。不部署独立 `file-mcp` 或 `docling-server`。File Worker、Agent Worker、Runtime、Delivery 和前端都不持有 MinIO 凭据；Worker 只使用平台身份服务轮换的短时、角色隔离 Principal JWT 调用 File Service。

采用该边界是因为让 File MCP 或 Worker 直接取得 MinIO 凭据会形成第二个文件事实入口，绕过不可变版本、配额、生命周期、审计和授权。它不同于 ONES MCP：ONES 凭据解析后的调用目标本身是外部业务系统，而 MinIO 是平台内部存储实现，不应成为 Agent 的业务授权资源。

Business Application Publication 冻结工作区、File MCP、Runtime Write/Edit 和默认交付四级开关；旧 Publication 全部关闭。初始能力仅支持 UTF-8 TXT；后续格式扩展必须继续经过同一个 File Service 边界，并按 ADR-0051 冻结版本化格式策略。群文件按同一企业、Connector 和 conversation ID 共享，但每次使用仍复核实际发送人和业务应用访问；不复制钉钉群成员 ACL。钉钉在线编辑在第一阶段不可自动感知，输出作为新钉盘文件交付，不覆盖输入原件。
