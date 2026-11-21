# 浏览器插件协议 v1

平台和插件按操作选择 `protocol.schema.json#/$defs/<名称>` 校验 JSON。协议信封和索引的字段固定。录制投影版本 2 支持开放的业务字段名与层级。客户端和服务端均须对字段来源、凭据、原始消息及字节配额进行检查；JSON Schema 的结构检查和常见凭据键名检查只覆盖其中一部分。

## 接通纯文字提问与流式回答

1. 打开插件控制台的「询问 Agent」。本期接入内网 HTTP 平台。首次使用时粘贴系统的 HTTP 地址（例如 `http://agent.intra:8080`），然后点「用系统账号登录」。插件会记住平台地址。
2. 在平台页面用自己的系统账号登录并确认首次授权。回到插件，选择业务应用，输入问题。列表只显示本人有权使用、已发布激活并启用了浏览器插件入口的应用。
3. 回答逐步显示在原会话。短时断网会自动续读，重新打开控制台后可查看已完成的回答。

管理员在系统内为业务应用启用「浏览器插件」入口，发布并激活应用，将使用权限分给相应角色。该入口使用已发布 Agent 上的插件连接，回复回到原插件会话。发行包和服务端内置同一插件身份。标准 Compose 启动时由 migrator 处理数据库升级。

## 接口

控制台选定已保存的录制后，会先在本机列出请求与操作数、缺口、字段样例和压缩前预计字节。用户点击共享后，插件上传 gzip 分片。重新打开控制台，选择同一录制并继续共享，插件会向平台查询缺片。录制发布后，第一次绑定会将版本 ID 发送给应用，后续提问沿用会话。纯文字提问也可单独使用。

需要查询录制的应用应发布包含 `search_recording` 和 `get_recording_evidence` 的 Agent，并给使用者的角色授予应用及这两个工具的权限。只有运行中的已绑定 Job 能检索其录制。File Service 把分片写入 MinIO，平台保存查询索引。检索和读取明细使用不同权限，读取单条明细时，平台对具体 Job、执行次数与证据签发短期内部授权。插件用户继续使用系统账号。

升级已有 Compose 环境时，管理员先对当前部署使用的凭据目录运行 `scripts/bootstrap_agent_runtime_secrets.sh`。新增的录制服务凭据只供 API 和 tool-mcp 使用。将 migrator、API、File Service、tool-mcp、管理前端、Agent Worker、Job Dispatch Worker 及两个 Python Runtime 更新到同一版本，由 migrator 升至 164。Job Dispatch Worker 也会核对工具契约，旧镜像会使已受理的提问等待重试。

迁移 164 建立录制、分片回执、索引及会话和 Job 引用。初始化的 JSON 清单最多 1 MiB，每片展开后最多 1 MiB，每个录制版本最多 256 MiB、100 万行。在同一平台来源下，每位用户可同时暂存 32 个录制版本，累计最多 512 MiB，暂存期为 24 小时。重复初始化沿用原到期时间。

业务接口前缀为 `/api/browser-extension`。初始化录制和提交问题须在 `X-Application-Scope` 回传应用列表提供的范围引用。身份由 Bearer 凭据确定。授权入口及错误符合配套 OpenSpec 的 PKCE 流程。

| 操作 | 输入 | 成功结果 |
| --- | --- | --- |
| POST /applications/{id}/recordings | InitRecording | UploadReceipt |
| PUT /recordings/{id}/parts/{n} | 每行一个 EvidenceRow，可用 Content-Encoding: gzip | PartReceipt |
| POST /recordings/{id}/complete | 空请求体 | ReadyReceipt |
| POST /applications/{id}/messages | CreateMessage，UTF-8 信封上限 64 KiB | 202 MessageReceipt |
| GET /applications/{id}/messages/{client_message_id} | 原应用与原消息标识 | MessageReceipt |
| GET /conversations/{id} | 可选 before（上一页返回的 Job ID）、limit（1 至 20） | ConversationPage，按会话顺序返回问题和 Job 引用。每个回答从对应 Job 的快照或流读取 |
| GET /jobs/{id} | 原 Job 标识 | Snapshot |
| GET /jobs/{id}/events | 可选 Last-Event-ID | text/event-stream，每帧 data 为一个 AnswerEvent |
| search_recording | SearchRecording，时间窗端点均包含，from_ms 不超过 to_ms | SearchResult |
| get_recording_evidence | GetRecordingEvidence | EvidenceResult |

SSE 的 id 为十进制文本，event 为事件名；两者分别与 data.id 的十进制表示和 data.event 一致。草稿及游标同时更新。快照的 through_cursor 覆盖该快照的全部状态，重连只追加此游标以后的事件。未收终态即断流时可读取快照。证据 ID 中的录制标识只用于与本轮 Job 的绑定核对。搜索结果按相对时间、种类和源 ID 排序，分页从最后一行之后继续。按关联证据查不到操作时，可按失败请求的 `offset_ms` 设置 `from_ms`、`to_ms` 检索附近操作，并在回答中说明时间邻近。

`answer_delta.text` 是 Markdown 原文片段，可在行内标记、表格或代码围栏中间断开。客户端保留对应 Job 和 attempt 的原文草稿，依游标追加后统一渲染。工具前后主对话助手的正文按顺序组成同一答复。`Snapshot.draft` 用于恢复原文，`completed.final_answer` 是持久全文，整体替换草稿。

Job 开始运行后会先发出 `analyzing` 状态，即使模型尚未生成公开正文。迁移 165 扩大模型调用记录的序号范围。新版 Worker 对插件原会话在冻结的 Runtime 1.5 请求中声明 `browser_preview_budget=separate-v1`。这类请求的正文预览有独立的 256 个事件、8 MiB 传输额度和 524288 字符上限。执行、审计和终态仍共用原来的 2048 个事件和 96 MiB 额度。旧请求沿用原预算。预览达到上限时，客户端继续等待权威终态。

业务错误直接返回 `{"code":"…"}`。插件凭据到期时返回 401 和 `credential_expired`。服务端停用整个插件连接时返回 403 和 `access_denied`，单个应用停用或无权读取具体资源时可返回 404。授权页收到有效的回调地址、客户端和 state 后，静默授权失败会在固定回调的查询参数中带回原 state 和错误分类。

## 确定性投影

- 输入为已封存录制。分别统计请求和操作，`saved = shareable + platform_excluded`，每个可共享源 ID 恰有一行。平台自身流量只计数。ID 集按 ASCII 字节序独立排序，在每个 ID 后附一个 LF，连接并取 SHA-256 小写十六进制；空集合对空字节取摘要。
- 行先按 kind（action、request）再按源 ID 的 ASCII 字节序排列。对象键按 UTF-16 编码单元递归排序后写出，数组保留顺序（关联按 eventId、basis 排序）。字符串与有限数值使用 ECMAScript JSON.stringify 的转义及数值表示；字符串不做 Unicode 规范化。编码为无 BOM 的紧凑 UTF-8，每行以单个 LF 结束。服务端按收到的展开字节核摘要，避免重新序列化改变字节。
- 投影版本 2 依上序贪心填入每片最多 1 MiB 的未压缩完整行，下一行将超限时另起一片。超过单片的单行拒绝，禁止拆行。片号从 0 连续递增，空录制使用空分片清单。片摘要和字节数均基于未压缩字节，重试可使用不同 gzip 压缩参数。摘要、唯一性或计数不符时不可发布。
- `request_capture`、`response_capture` 记录本地采集状态。请求、响应和操作的业务明细分别位于 `request_details`、`response_details` 和 `details`。每份明细的 `value` 支持嵌套对象、数组和 JSON 标量，`omissions` 用 JSON Pointer 记录受保护、未采集、截断或无法安全拆分的字段位置及原因。未知路径与新增字段可以直接查明细；查询时返回有界结果。请求或响应的字段状态为 `included` 时省略清单为空，`partial` 至少有一项省略。
- 上传前从数据来源识别登录、会话和平台自身流量，剔除凭据、原始业务消息及无法安全拆分的原文。普通日志只含计数与状态。字段名本身也可能含记录内容，省略说明只能使用可公开的结构路径，否则退至安全的父路径。
- 消息中省略 recording_id 表示沿用原会话，null 表示解除，给出 ID 表示切换。重试保留原信封，缺省与 null 不可互换。上传未提交、已就绪、已过期的状态以服务端回执为准。

`golden/` 包含两个封存版本的初始化请求和原样 NDJSON 字节，以及按顺序标明契约名的续传、消息重放、只读查询、快照、重试和终态样例。平台和插件可以对同一份文件比较字节和语义。
