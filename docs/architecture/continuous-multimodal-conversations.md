# 连续会话与渠道文件输入

本文只描述渠道消息如何进入 Session、Task Workspace 和 Agent Job。文件格式、版本、
Docling Representation、Sandbox 与交付细节以
[受治理任务文件工作区](task-file-workspaces.md) 为准。

## 事实边界

- PostgreSQL 保存 Channel Ingress、Session、Message、Attachment、Workspace、Job、
  Outbox、Delivery 和审计事实。
- RabbitMQ 只传稳定 ID、attempt 和 correlation，不传聊天正文、文件字节、下载凭据、
  对象位置或模型凭据。
- File Service 是原件、不可变版本和派生 Representation 的唯一对象存储入口；应用、
  Worker、Runtime 与 MCP JSON 不直接访问 MinIO。
- 文档解析由受治理的 `file-processing-worker -> docling-serve` 链完成，不在 Channel
  Ingress 或 Agent Worker 内同步解析。

## Session 归属

- 群聊按受信企业、Connector、Business Application route 和群 conversation ID 隔离；
  文件 Workspace 可在同群已授权用户间共享，但每条消息使用实际发送人重新鉴权。
- 私聊按 Connector、Business Application route、会话和当前内部用户隔离。
- 相同外部 ID 出现在不同企业、Connector、群/私聊或应用路由时不会共享 Session。
- 上下文由持久消息、受控摘要、最近消息和本 Job Manifest/Working Set 组成，按预算裁剪；
  不把整个 Workspace 或原始附件正文无界注入 Prompt。

## 纯附件与后续文字

```text
附件消息
  -> Channel Ingress 持久化
  -> File Worker 导入 File Service
  -> 可选 Docling 异步生成 Representation
  -> 暂存到当前 Session/Workspace

后续非空文字
  -> 只绑定本轮确定的附件/引用
  -> 创建或复用 Session/Workspace
  -> 冻结 Manifest v5 / Working Set
  -> 能力就绪后发布 Agent Job
```

纯附件不会为每个文件创建占位 Agent Job 或逐个回复。连续发送多个附件后，第一条相关
非空文字可以绑定本轮文件；已认领附件不会被后续无关文字重复消费。未被本轮绑定且仍在
处理的文档保留为目录候选，不应阻塞无文件依赖的文字请求。

如果本轮明确绑定的输入仍在导入或缺少必需 Representation，Job 可以保持
`WAITING_INPUT`；能力到达安全终态后只释放一次。失败、拒绝或处理不可用必须返回稳定
安全结果，不得把原始二进制直接交给 Agent 作为降级路径。

## 格式与 Profile

直接文本固定支持 TXT、只读 LOG 和 `.md`。PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP
只有在命中的 Application Publication 冻结 `docling-layout-ocr-v2` 时才进入文档处理；
Profile 为 `NONE` 时明确未启用。原始文档和图片不会进入 Agent Sandbox，Agent 读取的
是冻结的精确 Markdown Representation。

图片/OCR结果是外部不可信证据，不等同于完整视觉理解。Office 内嵌图片按原始图片像素
处理，不宣称应用了页面显示层裁剪、旋转或翻转。

## 凭据与内容安全

钉钉下载 code 在必要存续期内使用平台 Master Key 加密；下载完成、拒绝、最终失败或
过期后按生命周期清理。明文/密文、临时 URL、access token、session webhook、文件
正文、对象键和 Docling API Key 不得进入普通日志、RabbitMQ 或审计摘要。

## 当前 Compose

文件与文档处理服务已在当前 Compose 定义中，不使用旧 `attachments` 或
`dingtalk-stream` profile：

```bash
docker compose up -d --build \
  minio minio-init file-service file-worker \
  docling-serve file-processing-worker dingtalk-runtime
```

实际启动还依赖 migrator、PostgreSQL、RabbitMQ、API、受控 Secret/JWKS 和对应健康门禁；
不要把上述服务列表当成可脱离基础设施独立运行的完整命令。

## 验收

至少验证一条新鲜链路：

```text
DingTalk -> Ingress/Outbox -> File import -> optional processing
  -> Manifest/Working Set -> Python Runtime -> File MCP
  -> Job terminal -> Delivery exact version
```

同时检查重复消息、处理中/失败输入、权限撤销、Sandbox 清理、提交冲突和 Delivery 重试。
MinIO/Docling 容器 healthy 或合成测试通过都不能单独证明真实钉钉与模型 E2E。
