# 受治理文档处理运维

## 当前拓扑

```text
File Service persistent outbox
  -> RabbitMQ agent.file.processing.queue
  -> file-processing-worker + file-processing-worker-2 (各自 prefetch=1)
  -> docling-serve (单容器、两个 local execution workers)
  -> File Service staging/finalize
  -> immutable Representations
```

- 两个 `file-processing-worker` 实例使用相同镜像、角色、队列和只读配置，分别访问
  RabbitMQ、Identity API、File Service 和专用 Docling 网络；
  不持有 PostgreSQL、MinIO、平台 Master Key 或用户 Bearer Token。
- `docling-serve` 只加入 `document-processing` 内部网络，不发布宿主端口，不持有
  PostgreSQL、RabbitMQ、MinIO 或模型 Provider 凭据。
- File Service 仍是唯一持久对象存储边界。Docling 只接收 Worker 通过内部 multipart
  上传的单个原件，结果由 Worker 回传 File Service。
- 当前没有 Redis、RQ、Ray 或独立 `file-mcp`。每个处理 Worker 进程并发固定为 1，
  File Service 用 PostgreSQL 中恰好两个静态槽位保证全局 Docling 在途上限为 2。

## 当前 Profile 与格式

新 Business Application Revision 只接受：

- `NONE`：不处理 PDF/Office/图片；
- `docling-layout-ocr-v2`：处理 PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP。

`docling-text-v1` 和 `docling-layout-ocr-v1` 只可能出现在历史 migration/publication/run
解释中，不得由当前 API 新建、发布或重新激活。当前 migration head 为 `122`；不要按
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

File Service 冻结的处理器身份同时覆盖该镜像和代码内置的 DOCX 兼容算法：

```text
processor version: v1.30.0+wps-null-zero-drawing.v1
processor build digest: sha256:ea15a6fc35b991249180d9265e1a3406448855fe8134c61fc7d26dd046b93429
digest input: docling-serve@sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807|wps-null-zero-drawing/v1
```

当前代码唯一有效的 `docling-layout-ocr-v2` Profile hash 为：

```text
8a9ba792a902a8a2c9ede356ab1dd195fc1b3a0e192d96606c84b8331a3b7cb9
```

模型 artifact digest 仍为：

```text
sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c
```

Profile hash 由包含图片结果适配算法版本的代码 canonical payload 自动生成，模型
artifact digest 由镜像内容固化。Compose 不再要求
`DOCUMENT_LAYOUT_OCR_PROFILE_HASH` 或 `DOCLING_MODEL_ARTIFACT_DIGEST` 环境变量；部署到
其他环境时不得再手工替换它们。

兼容算法只在首次提交 Docling 前移除指向不存在 `../NULL`、且全部引用均为零宽或零高
DrawingML 图片占位的关系与节点。规范化副本仅存在于 Worker 内存，原始 File Version、
内容哈希和交付字节不变；可见图片、外部关系、混合关系或无法证明安全的结构以
`docx_null_image_placeholder_unsafe` 非重试失败。该算法升级必须改变 processor build
digest，但不得因为此兼容修复改变 `docling-layout-ocr-v2` Profile hash。

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

代码更新后的标准部署不需要改 Profile 参数：

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

`migrator` 会在 migration 前自动执行只读旧 Profile 排空预检。需要在部署前单独查看安全
计数时，可执行：

```bash
docker compose run --rm migrator python -m app.cli.docling_profile_cutover_preflight
```

输出只包含 Profile hash、parent/picture 非终态数量和外部 task 绑定数量，不包含文件名、
task ID、对象位置或凭据。`status=blocked` 时不要强行迁移或手工改库；保持旧版本 Worker
运行，等待旧 hash 的 parent、picture 和外部 task 全部进入终态后再重新部署。

要求：

1. migrator 最终 head 为 `122`；
2. File Service `/ready` 成功且 Principal JWKS、对象存储、processing outbox 可用；
3. Docling `/ready` 成功且固定模型 artifact/digest 可用；
4. File Service 聚合状态为 `READY`，且 `expected_workers=2`、`active_workers=2`、
   `eligible_workers=2`、`slots_total=2`、`slots_quarantined=0`；
5. RabbitMQ 的 processing queue consumer 数量恰好为 2，attachment queue 仍为 1；
6. 目标 Application Publication 明确冻结当前 `docling-layout-ocr-v2` 的
   code/version/hash。

Profile 配置存在但依赖不就绪时，管理面必须显示 `CONFIGURED_UNAVAILABLE`，不能伪造
`READY`。

可从管理端“文件操作”状态页查看上述聚合计数；命令行只做不含业务内容的拓扑检查：

```bash
docker compose ps
docker compose exec rabbitmq rabbitmqctl list_queues \
  name messages_ready messages_unacknowledged consumers
```

不要把容器 `healthy`、队列 consumer 数或空闲槽位单独当成业务验收完成。

## 旧 hash 应用重新发布

升级后，旧 hash 的 Revision、Publication 和 Deployment 仍能列出、查看和编辑，文档处理
组件显示 `CONFIGURED_UNAVAILABLE`，稳定原因是 `profile_version_unavailable`。这不等于管理
服务不可用，也不应阻止进入应用。

管理员按以下顺序显式切换：

1. 进入旧应用详情并创建新 Revision；系统按相同 Profile code 解析当前完整 Profile，冻结
   新 hash，不改写旧 Revision/Publication。
2. 检查新 Revision 的文档处理配置后发布。
3. 显式激活新 Publication；旧 hash Publication 的激活预检会返回
   `document_profile_version_unavailable`，但详情和编辑入口仍可用。
4. 激活完成后核对活动 route 已指向新 Publication。系统不会自动改绑旧 route、Job、run
   或历史 Representation。

## 槽位隔离处置

`slots_quarantined>0` 表示 Worker 无法证明外部 Docling task 已终止。此时系统有意失败关闭，
不得直接把槽位改成 `AVAILABLE`，也不得增加 Worker 或 Docling 副本绕过上限。

1. 暂停新文档处理准入，并停止两个 Processing Worker，保留 PostgreSQL、RabbitMQ、MinIO
   数据和卷：

   ```bash
   docker compose stop file-processing-worker file-processing-worker-2
   ```

2. 保存安全聚合计数和相关容器日志；日志证据不得包含上传文件、原始消息或 Secret。
3. 等待 Worker 心跳 TTL（90 秒）过期，重启唯一 Docling 容器并确认旧本地 task registry
   已清空。随后执行显式确认的受控恢复命令；若仍有有效 Worker 心跳，命令会失败关闭：

   ```bash
   docker compose restart docling-serve
   docker compose run --rm migrator \
     python -m app.cli.recover_docling_quarantine --confirm-docling-restarted
   docker compose up -d file-processing-worker file-processing-worker-2
   ```

   若无法证明 task 已不存在，保持隔离并升级处理，不要执行恢复命令或手工改库。
4. 恢复后等待同 owner 消息重投递；`docling_task_not_found` 会清除旧 task 绑定并在同一 run
   的后续 attempt 重新提交。重新确认无隔离槽位、在途不超过 2 和最终 Representation 完整。

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

固定并发变更至少再提交 10 个独立受支持文件，并记录：10 个独立 run/request、最大
Docling 在途为 2、其余消息可恢复等待、每个 run 的必需 Representation 恰好一份、队列
最终无消息丢失。在处理中终止一个 Processing Worker，确认未确认消息由同 owner 恢复，
而不是创建重复 task 或重复 Representation。

## 非破坏性回滚

先停止新文档准入并排空新 hash 非终态工作，再恢复旧代码、单 Worker 和 Docling 单执行器。
新 hash Publication 在旧代码下保持只读且不可激活；管理员只能显式重新激活旧代码仍支持
的旧 hash Publication。migration 121 是加法 migration，保留两个槽位表和心跳表，不删除
数据库行、不回滚卷、不改写历史 Publication、Job、run 或 Representation。
