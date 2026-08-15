# 受治理任务文件工作区

## 状态与边界

本文描述 `add-governed-task-file-workspaces` 的第一阶段实现。仓库测试证明代码路径；真实 PostgreSQL、MinIO、RabbitMQ、钉钉和目标环境 Secret 的部署验收仍是 deployment-gated。

第一阶段只支持 UTF-8 `.txt`：单文件最大 15 MiB、每工作区最多 20 个逻辑文件、未保留临时内容最多 100 MiB。输入可带 UTF-8 BOM，Agent 输出不带 BOM。DOCX、XLSX、PPTX、PDF、图片 OCR 和 Markdown 留到下一阶段由内部 `docling-serve` 统一解析；本阶段不部署 Docling，也不存在独立 `file-mcp` 容器。

## 两层工作区

```text
Agent Session
  -> Task Workspace（PostgreSQL 元数据 + MinIO 对象，可跨多个 Job）
       -> Job A Sandbox（Runtime 容器 tmpfs，终态删除）
       -> Job B Sandbox（Runtime 容器 tmpfs，终态删除）
```

任务工作区是会话内的逻辑文件上下文，不是本地目录。它由 Business Application Publication 冻结的 `DAY`、`WEEK` 或 `MONTH` 管理，按 Asia/Shanghai 自然周期计算固定到期时间，后续活动不延期。Job 沙盒仅属于一个 Job，位于所选 Runtime 容器的 tmpfs；成功、失败、取消、超时都清理，启动和周期扫描只清理没有 RUNNING Job 归属的残留目录。

消息附件和保留文件各自按 360 天独立保留，不会因工作区到期提前删除。内部 360 天副本清理后，即使钉盘文件仍存在且用户仍有权限，也不能用旧引用继续处理；用户必须重新发送或上传，形成新的消息附件和文件。

## 唯一文件入口

```text
Channel -> RabbitMQ -> File Worker -> File Service -> MinIO
Agent -> Runtime -> File MCP（File Service 内）-> File Service -> MinIO
Delivery Worker -> File Service -> DingTalk
```

File Service 是文件身份、不可变版本、当前版本、工作区引用、Job File Manifest、提交暂存、配额、生命周期、授权和审计的唯一入口，也是唯一持有 MinIO endpoint 与平台 Secret Reference 解析能力的业务容器。File Worker、Agent Worker、Python/TypeScript Runtime、Delivery Worker 和前端都没有 MinIO 凭据，也不能提交 Bucket、对象键、URL 或本地路径。

部署拓扑净新增一个 `file-service`；`file-worker` 替换旧 `attachment-worker` 并继续消费原附件队列；现有 Delivery Worker 保持独立。File MCP 是 File Service 的 Streamable HTTP 接口，不另起容器。

## 身份与授权

- Agent 使用平台签发的短时 Principal JWT，绑定内部用户、租户、Job、Session、Publication、授权 hash 和精确 Tool scope。
- File Worker 和 Delivery Worker 使用各自短时服务 Principal JWT 文件；File Service 只取得验证它们的服务 JWKS，不共享静态内部 Token。
- MinIO 原始凭据只由 File Service 通过 `secret://platform/` 解析，绝不进入 JWT、MCP 参数、日志、审计或模型上下文。
- 私聊工作区属于当前内部用户；群聊工作区以企业、Connector 和 conversation ID 共享，不复制钉钉群成员 ACL。每次操作仍要求实际 sender 已绑定内部身份、拥有当前业务应用访问且来自同一群。

## Job 文件链路

1. Channel 创建文件型 Job 时解析或创建 ACTIVE 工作区并冻结保留周期。
2. Job File Manifest 冻结本次消息附件、明确引用和其他工作区候选的精确版本；只包含有界元数据。
3. Runtime 根据 Manifest 通过 File Service 流式物化文件到 Job 沙盒；完整字节不进入模型或 MCP JSON。
4. Claude Code Agent 仅能在沙盒内使用受限 `Read`、`Grep`、`Write`、`Edit`。分析请求不得提交修改；修改或生成请求可逐文件创建提交意图。
5. Runtime 只上传显式选择的 sandbox entry。File Service 流式校验大小、UTF-8、摘要、配额和 base version，发布不可变版本。
6. 并发基于过期 base version 的结果成为 Conflict Candidate，不推进当前版本；File Service 不自动合并文本。
7. 默认文件交付开启时，成功精确版本创建固定 reply route 的 Delivery；“只保存到工作区”跳过。Delivery 失败只重试同一版本，不重跑 Agent、不回滚提交。

## 发布开关

Business Application Publication v3 冻结四个依赖有序的开关：

1. `workspace_enabled`
2. `file_mcp_enabled`（依赖工作区）
3. `runtime_file_edit_enabled`（依赖 File MCP）
4. `default_file_delivery_enabled`（依赖 Runtime 编辑）

旧 v1/v2 Publication 和未提供开关的 Job 稳定解释为全部关闭，保持原文字/附件行为。管理前端显示草稿值和发布快照来源。

## 钉钉在线编辑

第一阶段只知道附件导入时的快照，不能自动感知钉钉用户随后进行的在线编辑，也不轮询或消费钉盘变更事件。Agent 输出总是交付为新的钉盘文件，不覆盖输入原件。未来稳定钉盘引用和按需同步必须通过独立变更设计。
