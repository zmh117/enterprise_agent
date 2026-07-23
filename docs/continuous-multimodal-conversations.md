# 钉钉连续对话与多模态附件MVP

## 组件边界

- PostgreSQL 18是session、message、附件元数据、提取文本、滚动摘要、job和审计的唯一事实源。
- RabbitMQ 4只传`job_id`、`attachment_id`和`correlation_id`，不传文件、聊天正文或媒体凭证。
- MinIO/S3私有bucket保存原始附件。对象key使用内部attachment ID和SHA-256，不使用用户文件名。
- 本阶段不使用Agent专用Redis、pgvector、Qdrant、OpenSearch、Weaviate、Tika、LibreOffice、ClamAV、OCR或视觉模型。

## 会话边界

- 群聊：Channel + connector + project + 群conversation ID。
- 私聊：Channel + connector + project + 用户ID + 机器人身份。
- 相同外部ID出现在不同群/私聊、connector或project时不会共享上下文。
- 上下文由PostgreSQL滚动摘要、最近消息和READY附件文本组成，按配置预算裁剪。

## 附件支持

支持：

- JPEG、PNG、WebP：校验、去元数据并存储，状态为`stored_not_interpreted`；不作为诊断证据。
- DOCX：提取段落和表格文本。
- XLSX：只读、`data_only`，按工作表和行列上限提取，不执行公式。
- PPTX：按幻灯片提取文本。
- MD/Markdown：以UTF-8纯文本读取，不渲染HTML或远程资源。

拒绝：DOC、XLS、PPT、PDF、压缩包、音视频、SVG、脚本、可执行文件、宏/嵌入对象、加密/损坏或超限文档。

图片加文本时Agent只使用文本；仅图片时不调用模型并明确提示MVP暂不理解图片。

## 凭证安全

钉钉download code使用`APP_CONFIG_MASTER_KEY`以AES-GCM短期加密落库，RabbitMQ只传attachment ID。下载完成、拒绝、最终失败或过期后清除密文。明文/密文、临时URL、access token和session webhook不得出现在API、调试接口、日志或审计中。

## 本地启动

在业务应用草稿的 `session_policy` 中设置并显式发布：

```json
{
  "continuous_conversation_enabled": true,
  "attachments_enabled": true
}
```

对象存储凭据仍由部署环境或 Secret 管理：

```dotenv
S3_ACCESS_KEY=enterprise_agent
S3_SECRET_KEY=<local-secret>
S3_BUCKET=agent-attachments
```

启动附件profile和钉钉入口：

```bash
docker compose --profile attachments --profile dingtalk-stream up -d --build
docker compose --profile attachments ps
docker compose --profile attachments logs --tail=100 attachment-worker
```

MinIO API 宿主机默认端口 **19000**，控制台 **19001**（容器内仍是 9000/9001；`S3_ENDPOINT_URL=http://minio:9000`）。若需改映射，设置 `MINIO_API_PORT` / `MINIO_CONSOLE_PORT`。bucket 由 `minio-init` 幂等创建并保持匿名访问关闭。

## 处理与恢复

```text
PENDING -> DOWNLOADING -> EXTRACTING -> READY
                                └----> stored_not_interpreted
PENDING/DOWNLOADING/EXTRACTING -> REJECTED | FAILED
```

附件job先进入`WAITING_INPUT`。全部附件终态且存在文本或READY内容后原子转为`PENDING`并只发布一次Agent任务。瞬时下载失败进入延迟重试队列，超过重试次数进入附件死信队列。

孤儿对象核对默认只报告，不自动删除未知对象；过期清理只有对象删除成功后才把数据库记录标记为`DELETED`。

## 后续升级

1. 长期记忆：PostgreSQL增加memory事实表、证据和生命周期，再按需要安装pgvector。
2. 缓存：测量到会话读取负载、限流或流式状态需求后再增加独立Redis/Valkey；PostgreSQL仍是事实源。
3. 向量扩容：向量规模和延迟影响事务库后再接Qdrant。
4. 全文检索：出现海量文档、中文分词、高亮和复杂聚合后再接OpenSearch。
5. 文件能力：需要旧Office或开放下载时，再引入隔离Tika/LibreOffice和恶意软件扫描；需要理解图片时再接OCR/视觉模型。
