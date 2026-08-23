# 受治理文档处理运维

## 当前拓扑

```text
File Service persistent outbox
  -> RabbitMQ agent.file.processing.queue
  -> file-processing-worker
  -> docling-serve
  -> File Service staging/finalize
  -> immutable Representations
```

- `file-processing-worker` 访问 RabbitMQ、Identity API、File Service 和专用 Docling 网络；
  不持有 PostgreSQL、MinIO、平台 Master Key 或用户 Bearer Token。
- `docling-serve` 只加入 `document-processing` 内部网络，不发布宿主端口，不持有
  PostgreSQL、RabbitMQ、MinIO 或模型 Provider 凭据。
- File Service 仍是唯一持久对象存储边界。Docling 只接收 Worker 通过内部 multipart
  上传的单个原件，结果由 Worker 回传 File Service。
- 当前没有 Redis、RQ、Ray 或独立 `file-mcp`。处理 Worker 并发固定为 1。

## 当前 Profile 与格式

新 Business Application Revision 只接受：

- `NONE`：不处理 PDF/Office/图片；
- `docling-layout-ocr-v2`：处理 PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP。

`docling-text-v1` 和 `docling-layout-ocr-v1` 只可能出现在历史 migration/publication/run
解释中，不得由当前 API 新建、发布或重新激活。当前 migration head 为 `119`；不要按
旧 migration 113/116/117 cutover 步骤判断当前 schema 是否完整。

源文件最大 25 MiB，PDF 最多 300 页，单次处理上限 600 秒。Agent 只读取最终 Markdown
Representation；原件、Docling JSON、OCR Layout JSON、图片 asset 和 occurrence 不进入
Sandbox。Office 内嵌图片按原始图片像素处理，不宣称应用页面显示层裁剪、旋转或翻转。

## 固定镜像与安全配置

Compose 当前固定：

```text
quay.io/docling-project/docling-serve:v1.30.0
sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807
```

镜像使用非 root UID 1001、只读根文件系统、受限 tmpfs 和资源限制。远程 service、外部
插件、自定义 VLM/图片描述、UI、任意 URL 和运行时模型下载关闭，只允许 `inbody`
target。部署若改变 tag/digest、模型 artifact 或 Profile hash，必须重新核验，不能沿用
仓库内旧证据。

## Secret 自举

```bash
scripts/bootstrap_agent_runtime_secrets.sh /absolute/secret/directory
```

文档处理使用两个角色隔离文件：

- `file-processing-worker-bootstrap-token`：换取最长 300 秒的 Service Principal JWT；
- `docling-api-key`：只挂载到 `file-processing-worker` 与 `docling-serve`。

脚本不会覆盖完整已有材料；半套密钥或权限不合规时失败关闭。凭据不能写入 `.env`、
RabbitMQ、审计 payload、普通日志或证据文件。

## 启动与就绪检查

```bash
docker compose config --quiet
docker compose up -d --build \
  postgres rabbitmq migrator file-service \
  docling-serve file-processing-worker file-worker
docker compose ps
```

要求：

1. migrator 最终 head 为 `119`；
2. File Service `/ready` 成功且 Principal JWKS、对象存储、processing outbox 可用；
3. Docling `/ready` 成功且固定模型 artifact/digest 可用；
4. Processing Worker 同时报告 RabbitMQ、File Service、Docling ready；
5. 目标 Application Publication 明确冻结 `docling-layout-ocr-v2` 的 code/version/hash。

Profile 配置存在但依赖不就绪时，管理面必须显示 `CONFIGURED_UNAVAILABLE`，不能伪造
`READY`。

## 重试与清理

- RabbitMQ 消息只含 run/source version/profile hash/attempt/correlation ID，不含文档、
  对象位置、签名授权或凭据。
- 网络、超时和服务故障按有限退避重试；格式拒绝、结构超限和 schema 错误进入稳定终态。
- Worker 重启优先恢复 File Service 持久化的外部 task ID，避免重复 submit。
- `NO_TEXT` 不创建伪 Markdown；必需 Representation 未全部完成时不得暴露成功结果。
- 原件 staging、Docling 临时 task、图片 asset 和中间结果按各自生命周期清理；清理失败
  保持可重试事实，不通过删除数据库行伪装完成。

## 验收边界

至少用无业务数据的合成 PDF、DOCX、XLSX、PPTX 和图片验证：

```text
Publication -> Attachment ingress -> File import -> Processing outbox
  -> Worker/Docling -> Markdown/JSON/Layout representations
  -> Manifest v5 -> Python Runtime Markdown -> Agent result
  -> exact source file Delivery
```

同时覆盖幂等、重试、部分失败、超限、重启恢复、权限撤销和清理。容器 healthy、单元测试
或历史 synthetic E2E 不能证明当前目标环境、真实模型和真实钉钉 Delivery 已验收。
