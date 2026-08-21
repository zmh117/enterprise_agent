# Task File Workspace 切换与运行手册

本手册不授权真实环境写入。执行前必须确认目标、备份、镜像 digest、migration head、短时服务 Principal 签发/轮换和回滚窗口。不得把 JWT、MinIO 或钉钉凭据写入命令、工单或证据。

## 目标拓扑

- 新增 `file-service`，内部同时提供 File MCP 与受控流式 API；
- `file-worker` 替换 `attachment-worker`，继续消费原 `agent.attachment.queue`；
- Delivery Worker 保持独立并通过 File Service 读取精确版本；
- 不部署独立 `file-mcp` 或 `docling-server`；
- 只有 File Service 解析 MinIO Secret Reference。

## 1. 部署前只读检查

1. 验证 migration 精确到当前 catalog head，File Service 的统一 Principal JWKS、用户/Job 与服务身份验证策略、互不相同的新文件私有 Bucket 与旧附件私有 Bucket，以及固定 Tool Manifest readiness 均通过。旧附件 Bucket 只用于 File Service 执行 360 天到期清理，不把对象入口重新开放给 Worker。
2. 初始化统一平台 Principal 密钥/JWKS 与两个角色 bootstrap credential；脚本幂等保留现有材料，发现不完整统一密钥对时失败关闭：

```bash
scripts/bootstrap_agent_runtime_secrets.sh "${HOME}/.config/enterprise-agent"
```

   API Server 与 Agent Worker仅在签发对应Token时取得同一平台Principal签名私钥，File Service、ONES MCP及后续MCP只取得同一公开JWKS；File Worker与Delivery Worker各自只取得本角色bootstrap credential。Worker按需向固定内部API换取并在到期前刷新不超过300秒的JWT，不使用宿主机静态JWT文件。共享签名根不改变issuer、audience、authorized party与scope隔离，不得输出这些文件内容。
3. 运行 `docker compose config --quiet`，确认不存在 `file-worker-principal.jwt`、`delivery-worker-principal.jwt` 或对应静态 JWT 环境变量；再确认 API、File Service 和两个 Worker 的角色隔离挂载。
   本地首次启动还应设置 `FILE_STORAGE_SECRET_BOOTSTRAP_ENABLED=true`。一次性 Migrator 会把Compose中的`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`加密写入`minio-file-access-key`和`minio-file-secret-key`平台Secret；相同值幂等保留，已有值不同则停止并要求显式轮换。生产环境应预先配置受治理Secret并关闭此本地bootstrap。
4. 记录旧附件队列 `ready`、`unacked`、consumer 数、retry/dead 队列计数。切换前只能有一个附件消费者。
5. dry-run 回填，按返回的 `next_cursor` 循环；任何 `status=blocked` 都停止：

```bash
python -m app.cli.backfill_task_file_attachments --batch-size 100
python -m app.cli.backfill_task_file_attachments --reconcile --batch-size 100
```

命令只处理 PostgreSQL 关联和到期/清理事实，不下载、复制或删除对象。`unassociated_legacy` 表示旧内容没有跨过 File Service 边界，不能伪造为可处理版本；到期后用户必须重新上传。

## 2. 单消费者切换

1. 暂停旧 `attachment-worker`，不要清空或重建队列。
2. 等待旧消费者数变为 0、`unacked=0`；记录此时 `ready`。若无法归零，恢复旧 Worker 并停止切换。
3. 启动 File Service，等待 `/ready` 为 ready。
4. 启动 `file-worker`，确认原附件队列 consumer 数精确为 1、File Worker 状态同时显示 `rabbitmq=ready` 和 `file_service=ready`。
5. 用无真实业务内容的合成 TXT 发布一条消息；验证 attachment ID 幂等、File/Version/Workspace/来源关联、Job 释放和安全审计。
6. 重新投递同一附件队列消息，确认没有第二个版本或对象；再观察 retry/dead 与 lifecycle backlog。
7. 在维护窗口授权后执行有界写回填，每批用上一批 `next_cursor` 继续，直到 `has_more=false`：

```bash
python -m app.cli.backfill_task_file_attachments --apply --batch-size 100
```

8. 再运行 `--reconcile`；只有 `status=ready` 且关联差异为零才能关闭切换窗口。`unassociated_legacy` 可非零，但必须记录为只可重新上传的历史内容。

## 3. 验证与观察

- 平台运维页显示 File Service/File Worker 接线、单消费者、ready/unacked、附件/暂存/工作区/保留/冲突积压、最早到期和最近清理结果；
- 页面和 API 不得出现文件名、正文、Bucket、对象键、Secret 或 JWT；
- Runtime readiness显示非敏感容量上限，并精确验证Sandbox v2为64个文件/224 MiB、`inputs=40`、`work/outputs=16`、`tmp=8`和15 MiB单文件限制；默认容器tmpfs仍为256 MiB，任一配置漂移或可用空间不足224 MiB均失败关闭；
- Publication 四项文件开关先保持全关，格式策略保持 `text-v1`。管理目录中的 `text_v2_cutover_preflight.ready` 必须为 `true`；若列出引用旧 File MCP schema hash 的 `WAITING_INPUT/PENDING/RUNNING/RETRY_WAIT` Job，必须先排空或在受控队列外隔离，禁止发布或激活 `text-v2`；
- 发布一个使用受支持Runtime protocol v1.2或v1.3、且冻结当前精确File MCP schema hash的Agent Publication，再按应用发布/激活`text-v2`。目录revision与Manifest v5不要求Runtime协议升级；不得修改旧Publication或旧Job Snapshot；
- 用合成`.txt`、通用MIME `.log`和`.md`验证混合纯附件认领、Manifest v5、Markdown提交与精确版本交付；确认LOG的Write/Edit/Commit/改名绕过均在副作用前失败，`.markdown`仍走旧附件兼容链而不进入工作区；
- 至少观察附件重试、短时服务 JWT 到期前刷新、身份服务/File Service 短暂不可用恢复、交付响应丢失重试和到期清理。

## 4. 大工作区分阶段启用

1. 先应用migration 118并部署支持tenant Runtime Config的Control Plane/管理端，但暂不替换File Service、Agent Worker和Python Runtime，也不切换Publication流量。
2. 通过受治理管理API枚举并逐一确认既有tenant，为每个tenant显式写入20个ACTIVE文件和100 MiB计费字节覆盖；不得直接改表。重新读取诊断，确认两个值的来源均为`db:tenant`且配置审计完整。任何未覆盖tenant都阻止进入下一阶段。
3. 再部署File Service、Agent Worker、Python Runtime和新Tool代码；确认既有tenant的有效值仍是20/100 MiB、Sandbox v2 readiness精确通过，且未改变既有Publication。
4. 在`/platform/runtime-config`选择目标tenant，确认诊断中的实际/预留用量、有效来源和revision；只读兼容预检必须为空。不得用业务请求、Agent参数或原始SQL声明tenant配置上下文。
5. 发布并激活一个冻结`task_workspace_search_files`、`file_prepare_materialization`及必要File MCP工具的兼容Application Publication；先用合成数据验证“冻结目录分页搜索→精确File/Version选择→预算预留→物化”。
6. 完成200/1000文件、2/10 GiB、50项分页、40输入和64文件/224 MiB压测与真实全链E2E后，再以管理API的expected revision把目标tenant改为200个ACTIVE文件与2 GiB。配置审计必须记录操作者、旧/新revision和兼容预检摘要。
7. 变更后观察配额拒绝、目录搜索、Sandbox预检、Docling队列、Job失败率与延迟；不得把容器healthy当作业务验收。

## 5. 回滚

1. 停止向新兼容Publication路由新流量；使用新的追加式Application Revision恢复到上一份已验证的Publication，不改写既有Publication或Job Snapshot。
2. 在`/platform/runtime-config`读取目标tenant当前revision，以CAS把ACTIVE文件上限恢复为20、计费字节上限恢复为104857600；不得绕过管理API直接改表。若CAS冲突，重新读取并人工确认后再提交。
3. 已超过回滚配额的工作区保持现有内容可授权读取和精确交付，但新增逻辑文件、版本、staging或派生表示在对应超限维度失败关闭；不得删除用户内容以迎合新上限。
4. 保留migration 118、目录revision/成员、Job工作集、Manifest、配额预留、审计与Delivery事实；不回退migration、不删除ledger、不重写对象键。
5. 若同时回滚File Worker，先停止`file-worker`并等待consumer=0、`unacked=0`；只在既有兼容窗口内恢复已验证的旧Worker，且始终保持单消费者。
6. 继续观察超限拒绝、历史Job读取和清理任务，直到新流量、队列和审计均稳定；需要恢复扩容时重新执行兼容预检和真实E2E。

## Stop conditions

任一条件立即停止：多个附件消费者；unacked无法归零；`text_v2_cutover_preflight`或tenant兼容预检存在blocker；Runtime协议不受支持、Sandbox v2 readiness漂移或File MCP hash漂移；Service Principal材料不完整、角色挂载交叉或短时JWT无法签发/验签；File Service/JWKS/Bucket未ready；回填`blocked`；消息幂等产生重复版本；LOG产生Commit Intent/新版本；Worker/Runtime/Delivery获得MinIO凭据；审计或UI泄漏正文、对象位置、bootstrap credential或JWT；没有经验证的回滚镜像和备份。
