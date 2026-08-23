# 受治理任务文件工作区

## 当前边界

File Service 是文件身份、不可变版本、当前版本、Task Workspace、目录 Revision、Job
Working Set、Manifest、Representation、提交暂存、配额、生命周期、授权、审计和对象
位置的唯一事实入口，也是唯一持有 MinIO 凭据的业务服务。

```text
Channel -> file-worker -> File Service -> MinIO
File Service outbox -> file-processing-worker -> docling-serve
Python Runtime -> File MCP（File Service 内）-> File Service
Delivery Worker -> File Service -> DingTalk
```

当前有独立 `file-service`、`file-worker`、`file-processing-worker` 和
`docling-serve` 服务，但没有独立 `file-mcp` 容器。Agent Worker、Python Runtime、
File/Processing/Delivery Worker 和前端都不能获得 MinIO Bucket、对象键或凭据。

## Workspace 与 Job Sandbox

```text
Agent Session
  -> Task Workspace（PostgreSQL 元数据 + MinIO 对象，可跨多个 Job）
       -> Job A Working Set / Manifest v5
       -> Job A Sandbox（Python Runtime tmpfs，终态清理）
```

一个 Session 可以有多个历史 Workspace，但同一时刻最多一个 ACTIVE。没有活动
Workspace 时，普通文字问答不会创建 Workspace；首个文件输入或文件产出请求才创建。
到期/关闭 Workspace 不会自动恢复。私聊 Workspace 属于当前内部用户；群聊按受信企业、
Connector 和 conversation ID 共享，但每次操作仍以当前发送人复核应用访问和同群边界。

Workspace 保留周期由 Application Publication 冻结为 `DAY`、`WEEK` 或 `MONTH`，按
Asia/Shanghai 自然周期计算固定到期时间，后续活动不顺延。文件/附件的独立保留和
Workspace 生命周期是不同事实；过期 Workspace 不能靠旧引用恢复为 ACTIVE。

## 当前格式与配额

直接文本规则在代码中固定为 `text-v2`，不是 Publication 或 Runtime 可选择的扩展点：

| 格式 | 读 | 创建/编辑/提交 | 交付 |
|---|---:|---:|---:|
| UTF-8 `.txt` | 是 | 是 | 是 |
| UTF-8 `.log` | 是 | 否 | 仅既有精确版本 |
| UTF-8 `.md` | 是 | 是 | 是 |

`.markdown` 不进入 Workspace。文本和 Agent 可读 Markdown 单文件最大 15 MiB；输入可带
UTF-8 BOM，Agent 输出不能带 BOM；NUL、无效 UTF-8、UTF-16/GBK 和二进制伪装失败
关闭。Markdown 只是不可信纯文本，不渲染 HTML、不解析链接、不抓取远程资源。

当 Application Publication 冻结 `docling-layout-ocr-v2` 时，还接受不超过 25 MiB 的
PDF、DOCX、XLSX、PPTX、PNG、JPEG 和 WebP；PDF 最多 300 页。原始二进制不会进入
Agent Sandbox，Agent 只读取受治理的 Markdown Representation。Profile 为 `NONE` 时，
这些格式明确拒绝且不调用 Docling。DOC、XLS、PPT、宏文件和其它未注册格式不支持。

当前 Workspace 默认配额为 200 个 ACTIVE 逻辑文件和 2 GiB 计费内容；tenant 可通过
受治理 Runtime Config 调整，代码硬上限分别为 1000 个文件和 10 GiB。Job Sandbox
固定最多 64 个普通文件和 224 MiB，其中 inputs 最多 40，work/outputs 合计最多 16，
Runtime tmp/安全余量最多 8。所有入口在副作用前预留配额，不做部分导入或静默截断。

## 附件、Working Set 与 Manifest v5

1. 纯附件消息先进入 Session/Workspace 的暂存集合，不单独创建 Agent Job。
2. `file-worker` 通过 File Service 导入原件；需要文档处理时由持久 Outbox 触发
   `file-processing-worker` 和 Docling。
3. 后续非空文字只绑定本轮确定的附件/引用并创建 Job；真正被本轮绑定且能力未就绪的
   输入可以让 Job 等待，未绑定的处理中候选不会阻塞无文件依赖的文字 Job。
4. Job 冻结 schema v5 Manifest：目录 Revision ID、Working Set、精确 File/Version、
   精确 Representation、格式/操作、大小/hash 和时间语义。当前服务拒绝 v1-v4。
5. 当前附件和明确绑定输入可以自动物化；其他 Workspace 文件只通过冻结目录 Revision
   分页搜索，再由 Agent 选择精确 File/Version。累计不同输入最多 40 个。
6. Manifest 冻结身份，不冻结长期授权；每次物化、提交和交付都重新检查当前用户、应用、
   Job、Session、Publication 和 scope。

时间字段必须区分：聊天附件进入平台的 `source_received_at`、精确版本生成的
`version_created_at`、Representation 生成时间和本次查询/Manifest 的 `observed_at`。
Agent 生成文件没有上传时间，`source_received_at=null`。回答“最近一小时上传”时只能
用 `source_received_at` 相对 `observed_at` 判断。

## Runtime 文件操作

Python Runtime 只把当前 Manifest/Working Set 授权的精确文本版本或 Markdown
Representation 物化到 Job Sandbox。Claude Code Agent 仅可使用受限的 `Read`、
`Glob`、`Grep`、`Write`、`Edit`；Bash、Web、NotebookEdit、沙盒外路径、符号链接和
原始 PDF/Office/图片均不可用。

Agent 新建或修改文件后，必须显式选择 `work/` 或 `outputs/` 下的单个 TXT/Markdown，
再创建 File MCP commit intent。File Service 重新校验格式、大小、hash、配额和 base
version，成功后发布不可变新版本。过期 base version 形成 Conflict Candidate，不覆盖
当前版本，也不自动合并。

默认文件交付开启时，系统只投递本次明确提交的精确版本；“只保存到工作区”跳过交付。
Delivery 失败只重试同一版本，不重跑 Agent，也不回滚提交。

## Publication 开关

Application Publication 冻结四个有依赖顺序的开关：

1. `workspace_enabled`
2. `file_mcp_enabled`
3. `runtime_file_edit_enabled`
4. `default_file_delivery_enabled`

启用 Workspace 同时要求 Session Policy 开启连续会话和附件。文档处理另由
`document_processing_profile_code=NONE|docling-layout-ocr-v2` 冻结。开关、Profile、
Tool schema 或 Runtime protocol 不兼容时，校验/发布/激活失败关闭；不会修改旧
Publication 或把旧 Job 静默升级。

## 验收边界

仓库测试能证明 schema、授权、配额、格式、冲突、重试和清理合同，但不能代替目标环境
的 PostgreSQL、RabbitMQ、MinIO、Service Principal、Docling、Python Runtime 和真实
钉钉 Delivery 全链验收。`healthy` 只证明进程探针，不证明文件业务链完成。
