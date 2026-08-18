# 受治理文档处理运维

## 净新增拓扑

本能力只增加两个运行服务：

```text
File Service Outbox -> RabbitMQ file-processing queue
  -> file-processing-worker -> Docling Serve
  -> File Service representation staging/finalize
```

- `file-processing-worker` 只能访问 RabbitMQ、Identity API、File Service 和专用内部
  Docling 网络。它没有 PostgreSQL、MinIO、平台 Master Key 或用户 Bearer Token。
- `docling-serve` 只加入 `document-processing` 内部网络，不发布宿主端口，不持有
  PostgreSQL、RabbitMQ、MinIO 或模型供应商凭据。
- File Service 仍是唯一持久对象存储边界。Docling 只接收 Worker 通过内部 multipart
  上传的单个原件，结果由 Worker 回传 File Service。
- 第一阶段不引入 Redis、RQ、Ray 或 `file-mcp`。Docling 使用 local engine，处理
  Worker 并发固定为 1。

## 固定发布物与安全配置

Compose 固定官方多架构镜像，并通过环境配置强制 CPU 执行：

```text
quay.io/docling-project/docling-serve:v1.30.0
sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807
```

镜像使用上游非 root UID 1001、只读根文件系统、受限 tmpfs、CPU/内存/PID 限制。
远程 services、外部插件、自定义 VLM/图片描述/公式配置、UI、管理接口和运行时模型
下载均关闭；只允许 `inbody` target。输入上限为 25 MiB、PDF 300 页、处理 600 秒。

当前发布核验已确认版本、multi-arch digest、amd64/arm64 manifest、MIT 许可证和
SLSA provenance。镜像 SBOM 尚未取得可审计证据，因此不能把生产启用的 SBOM 门禁表述为完成；
详见 OpenSpec change 的 `evidence/preflight.md`。

## Secret 自举

使用既有脚本生成或补齐角色隔离的文件凭据：

```bash
scripts/bootstrap_agent_runtime_secrets.sh /absolute/secret/directory
```

新增文件：

- `file-processing-worker-bootstrap-token`：Worker 向 Identity API 换取不超过 300 秒的
  Service Principal JWT；
- `docling-api-key`：只挂载到 `file-processing-worker` 与 `docling-serve`。

脚本不会覆盖已存在文件。所有新增凭据文件权限必须为 `0400`，不得写入 `.env`、日志、
RabbitMQ 消息、审计 payload 或数据库。

## 启动与门禁

1. 先执行 migration 113，确认 File Service `/ready` 返回 200。
2. 执行 `docker compose config --quiet`，确认 Compose 结构有效。
3. 启动 `docling-serve`，等待 `/ready` 成功；首次加载内置模型可能较慢。
4. 启动 `file-processing-worker`。其健康检查要求 RabbitMQ、File Service、Docling 均
   可用，状态文件和 heartbeat 在容器 tmpfs 中。
5. 业务应用仍默认 `NONE`。只对一个测试 publication 发布 `docling-text-v1`，再观察
   backlog、延迟、失败率、内存峰值和 DLQ。

不得仅凭容器 healthy 宣布业务能力完成。发布证据必须覆盖一条真实
Runtime→Inbox→Outbox→RabbitMQ→Job→processing worker→Docling→representation→
Runtime→Delivery 链路，以及失败、重试、重启和清理路径。

## 重试、DLQ 与处置

- 处理消息只包含 run/source version/profile hash/attempt/correlation ID，不包含文档、
  对象地址、签名授权或凭据。
- 网络、超时和服务故障按 30 秒指数退避，最多 3 个 attempt；格式拒绝、结构超限和
  无法恢复的 schema 错误直接进入稳定终态并投递安全 DLQ 摘要。
- Worker 重启时优先恢复 File Service 中持久化的 Docling task ID，避免重复 submit。
- `NO_TEXT` 不创建伪 Markdown；任一表示未完成时不得原子暴露成功结果。
- DLQ 和日志只保留稳定错误码及 ID。原始文档、完整提取文本、API Key 和 source grant
  一律不得进入诊断面。

## 当前发布限制

- CPU 脱敏样本基准尚未执行；并发保持 1，不得扩大或启用 GPU。
- SBOM 证据尚未取得；若生产门禁要求 SBOM，必须先补齐并重新核验 digest。
- 在完成 synthetic E2E 和真实全链路证据前，管理面必须显示
  `CONFIGURED_UNAVAILABLE`，不得显示 `READY`。
