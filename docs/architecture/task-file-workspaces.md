# 受治理任务文件工作区

## 状态与边界

本文描述已归档的基础工作区能力及 `support-log-and-markdown-workspace-files` 扩展。仓库测试证明代码路径；真实 PostgreSQL、MinIO、RabbitMQ、钉钉和目标环境 Secret 的部署验收仍是 deployment-gated。

Publication 冻结 `text-v1` 或 `text-v2`。`text-v1` 仅支持 UTF-8 `.txt`；`text-v2` 支持 TXT 全生命周期、LOG 只读和既有精确版本交付、Markdown 全生命周期。三种格式单文件最大 15 MiB，每工作区最多 20 个逻辑文件、未保留临时内容最多 100 MiB。输入可带 UTF-8 BOM，Agent 输出不带 BOM；NUL、无效 UTF-8 与二进制伪装失败关闭。Markdown 始终是不可信纯文本且不渲染，`.markdown` 不进入工作区。本能力不部署 Docling，也不存在独立 `file-mcp` 容器。

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
Agent -> Runtime 本地 File MCP Bridge -> File MCP（File Service 内）-> File Service -> MinIO
Delivery Worker -> File Service -> DingTalk
```

File Service 是文件身份、不可变版本、当前版本、工作区引用、Job File Manifest、提交暂存、配额、生命周期、授权和审计的唯一入口，也是唯一持有 MinIO endpoint 与平台 Secret Reference 解析能力的业务容器。File Worker、Agent Worker、Python/TypeScript Runtime、Delivery Worker 和前端都没有 MinIO 凭据，也不能提交 Bucket、对象键、URL 或本地路径。

部署拓扑净新增一个 `file-service`；`file-worker` 替换旧 `attachment-worker` 并继续消费原附件队列；现有 Delivery Worker 保持独立。File MCP 是 File Service 的 Streamable HTTP 接口，不另起容器。

## 身份与授权

- Agent 使用平台签发的短时 Principal JWT，绑定内部用户、租户、Job、Session、Publication、授权 hash 和精确 Tool scope。
- 平台只维护一套 Ed25519 Principal 签名私钥和公开 JWKS；API 身份模块与 Agent Worker仅在签发对应Token时取得同一私钥，File Service、ONES MCP及后续MCP只取得同一公开JWKS。用户/Job与Service Principal仍按独立issuer、audience、authorized party、claims和scope验证策略失败关闭。
- File Worker 和 Delivery Worker 各自只持有角色隔离的 bootstrap credential，向固定内部身份端点按需换取并到期前刷新不超过 300 秒的服务 Principal JWT；不在宿主机保存静态服务 JWT，也不共享内部 Token。
- `file-worker` 的固定 JWT 同时包含附件导入和内容清理 scope；`delivery-worker` 只包含精确版本交付读取 scope。File Service 校验完整角色 scope 集合后再校验当前端点所需 scope。
- MinIO 原始凭据只由 File Service 通过 `secret://platform/` 解析，绝不进入 JWT、MCP 参数、日志、审计或模型上下文。
- 私聊工作区属于当前内部用户；群聊工作区以企业、Connector 和 conversation ID 共享，不复制钉钉群成员 ACL。每次操作仍要求实际 sender 已绑定内部身份、拥有当前业务应用访问且来自同一群。

## Job 文件链路

1. 只有附件、没有非空文字时，Channel 创建或复用 ACTIVE 工作区并把附件加入同一 Session 的未消费集合；不创建 Agent Job、Dispatch、Delivery、占位指令或用户回复。
2. File Worker 正常下载并通过 File Service 导入附件；附件尚未被文字认领时只标记 `staged`。连续发送多个文件不会逐个触发回复。
3. 第一条后续非空文字在同一事务中创建唯一 Agent Job并认领该 Session/Workspace下全部未消费附件。若导入未完成，Job保持 `WAITING_INPUT`，最后一个附件进入安全终态后只释放一次。
4. Job File Manifest 冻结该 Job认领的附件、同消息附件、明确引用和其他工作区候选的精确版本；已认领附件不会被后续无关文字再次作为新上传自动消费。
   Manifest schema v3 同时冻结 `file_format_policy_version`、format code、精确版本、允许操作、`source_received_at`（平台收到原始聊天附件）、`version_created_at`（精确版本产生时间）和 `observed_at`（清单冻结边界）。旧 schema 稳定按 TXT-only 读取。File MCP 文件列表与精确元数据使用相同字段；Agent 生成文件的 `source_received_at` 为空。判断“最近一小时上传”只比较 `source_received_at >= observed_at - 1小时`，不能使用 File Worker完成时间、版本时间或通用 `created_at`。
5. Claude SDK 只连接 Runtime 代码注册的本地 `files` MCP。该 bridge 代理 Job 冻结的远端 File MCP 工具，并在 ToolResult 交回模型前拦截隐藏传输控制信息；Runtime 使用当前 Job File Principal JWT 从 File Service 流式物化精确版本到 Job 沙盒。完整字节、JWT、URL 和对象位置不进入模型或 MCP JSON。
6. Claude Code Agent 仅能在沙盒内使用受限 `Read`、`Glob`、`Grep`、`Write`、`Edit`。TXT/LOG/Markdown 可读，只有 TXT/Markdown 可写；LOG 写入在文件系统副作用前拒绝。分析请求不得提交修改；修改或生成请求可逐文件创建提交意图。
7. 物化输入由 bridge 自动登记 sandbox entry；新生成文件必须显式调用 Runtime 自有的 `select_sandbox_output`，且只能选择 `work/` 或 `outputs/` 下经过路径、格式操作、常规文件、符号链接、15 MiB 和 UTF-8 校验的单个 TXT/Markdown。Runtime 不扫描沙盒，也不自动提交其它草稿。
8. File MCP 创建提交意图后，bridge 在结果交回模型前只上传该 handle 映射的精确文件。File Service 流式校验大小、UTF-8、摘要、配额和 base version，发布不可变版本。
9. 并发基于过期 base version 的结果成为 Conflict Candidate，不推进当前版本；File Service 不自动合并文本。
10. 默认文件交付开启时，成功精确版本创建固定 reply route 的 Delivery；“只保存到工作区”跳过。Delivery 失败只重试同一版本，不重跑 Agent、不回滚提交。

## 发布开关

Business Application Publication v4 冻结文件格式策略和四个依赖有序的开关：

1. `workspace_enabled`
2. `file_mcp_enabled`（依赖工作区）
3. `runtime_file_edit_enabled`（依赖 File MCP）
4. `default_file_delivery_enabled`（依赖 Runtime 编辑）

启用任务工作区时，管理端同时强制开启消息附件和连续会话；后端也拒绝缺少任一依赖的草稿。这样纯附件与后续文字才能稳定落入同一个 Channel Session。

`text-v2` 还要求 Agent Publication 声明 Runtime protocol v1.3，并冻结当前代码注册的精确 File MCP schema hash。旧 Application Publication 缺失格式字段时稳定解释为 `text-v1`；旧 Agent Publication 只兼容 Runtime protocol v1.0-v1.2，不得处理 `text-v2` Job。管理前端显示草稿值、兼容状态和发布/Job快照来源，不提供任意格式配置入口。

## 钉钉在线编辑

第一阶段只知道附件导入时的快照，不能自动感知钉钉用户随后进行的在线编辑，也不轮询或消费钉盘变更事件。Agent 输出总是交付为新的钉盘文件，不覆盖输入原件。未来稳定钉盘引用和按需同步必须通过独立变更设计。
