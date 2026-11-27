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
| GET /applications | 当前插件登录账号 | BrowserApplications。保留原 environments；workshop_scopes 返回本应用已授权的环境、基地、车间组合及各级 ID、编码、名称。仅展示三个节点均启用、且单条角色应用授权同时覆盖范围和录制工具的组合。 |
| GET /applications/{id}/workshop-bindings | 当前应用范围 | 本人仍可访问的规则、三级范围 ID、绑定 ID、版本及启停状态。每个来源第一条返回的绑定携带 `reserved_paths`，列出本人已配置但已失权的路径边界，仅包含 path 和 hash_path。空数组表示边界已核对。 |
| PUT /applications/{id}/workshop-bindings | rule（origin、path、hash_path、query）、三级范围 ID、expected_revision | 新建传版本 0，修改或重新启用传当前版本；过期版本或重叠规则返回 409 |
| DELETE /applications/{id}/workshop-bindings/{binding_id} | expected_revision | 204，保留历史版本 |
| POST /applications/{id}/live-recordings | RegisterLivePages | 登记本场录制以及各个标签、文档和绑定版本，可幂等重试 |
| POST /applications/{id}/live-evidence | LiveBatch，单批最多 512 KiB | accepted 与 delivery=forwarded |
| POST /applications/{id}/live-evidence/verify | 录制 ID、来源、事件 ID、对象摘要与起始片号 first | 从 Loki 读回的逐片摘要 digests、下一片号 next 和可见状态 visible |
| POST /applications/{id}/recordings | InitRecording | UploadReceipt |
| PUT /recordings/{id}/parts/{n} | 每行一个 EvidenceRow，可用 Content-Encoding: gzip | PartReceipt |
| POST /recordings/{id}/complete | 空请求体 | ReadyReceipt |
| POST /applications/{id}/messages | CreateMessage，UTF-8 信封上限 64 KiB | 202 MessageReceipt |
| GET /applications/{id}/messages/{client_message_id} | 原应用与原消息标识 | MessageReceipt |
| GET /conversations | 可选 application_id、before、limit | ConversationList，按最近活动分页返回当前账号在此来源仍可访问的插件会话。指定业务应用时只返回该应用的会话 |
| GET /jobs/{id}/activity | 本人获授权的插件 Job | JobActivity，当前尝试的公开过程说明及该 Job 的工具调用、状态和安全摘要 |
| GET /conversations/{id} | 可选 before（上一页返回的 Job ID）、limit（1 至 20） | ConversationPage，按会话顺序返回问题和 Job 引用。每个回答从对应 Job 的快照或流读取 |
| GET /jobs/{id} | 原 Job 标识 | Snapshot |
| GET /jobs/{id}/events | 可选 Last-Event-ID | text/event-stream，每帧 data 为一个 AnswerEvent |
| search_recording | SearchRecording，时间窗端点均包含，from_ms 不超过 to_ms | SearchResult |
| get_recording_evidence | GetRecordingEvidence | EvidenceResult |

会话页的 `asked_at` 和成功答复的 `answered_at` 分别取自提问和最终回答的消息时间。完成快照与完成事件提供相同的 `duration_ms`，从任务创建计至完成，包含排队和重试。缺少任务完成时间的旧记录以最终回答时间为准，无法取得有效时长时省略该字段。

SSE 的 id 为十进制文本，event 为事件名；两者分别与 data.id 的十进制表示和 data.event 一致。草稿及游标同时更新。快照的 through_cursor 覆盖该快照的全部状态，重连只追加此游标以后的事件。未收终态即断流时可读取快照。证据 ID 中的录制标识只用于与本轮 Job 的绑定核对。搜索结果按相对时间、种类和源 ID 排序，分页从最后一行之后继续。按关联证据查不到操作时，可按失败请求的 `offset_ms` 设置 `from_ms`、`to_ms` 检索附近操作，并在回答中说明时间邻近。

`answer_delta.text` 是 Markdown 原文片段，可在行内标记、表格或代码围栏中间断开。客户端保留对应 Job 和 attempt 的原文草稿，依游标追加后统一渲染。新 Worker 在冻结的请求中声明 `browser_answer_parts=turns-v1`。支持该能力的 Runtime 按主会话的 SDK 消息边界提交公开过程说明，由结果消息或最后的答复提供最终正文。过程标记投影为 `replace=true` 的空增量以清除先前草稿。过程正文可从 activity 读取，最终答案独立保存。旧版已保存的合并回答仍按原文展示。`Snapshot.draft` 用于恢复原文，`completed.final_answer` 是持久全文，整体替换草稿。

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

### 持续采集登记

在同一来源内按路径段匹配当前路径及其子页面，先取最具体的路径，再取最具体的 hash 路由。显式定位键必须唯一并符合所选规则。同级路径可分别绑定不同范围，站点根目录 `/` 可显式绑定为站点默认范围。更具体路径遇到失权、撤销或定位键不匹配时停止匹配。旧 API 未声明路径边界时，插件保留精确匹配。

站点设置接受手动输入的 HTTP(S) URL，也可以从已打开的标签页选取。每条规则只选择一次业务应用，环境必选，基地和车间可逐级选填。应用目录的 `binding_scopes` 列出当前账号在该应用中可保存的完整组合。只有车间授权时，必须选到对应车间。

迁移 171 后，平台 PostgreSQL 的 `browser_workshop_binding` 按平台来源、账号、应用和规则版本保存 URL 匹配条件、环境、可空的基地和车间、悬浮开关。修改匹配条件、应用或关联范围会创建新版本。单独调整显示开关即时生效，可沿用当前采集登记。插件在 `chrome.storage.local` 缓存当前账号的规则，主机访问权限由各浏览器单独授予。关闭悬浮助手后仍可对匹配页面开启持续采集。

同一文档在同一应用和完整绑定范围内导航时沿用已有登记。单页应用切换到另一层级、另一范围或超出绑定范围时暂停，刷新或重新打开后重新匹配。

插件以当前账号凭据和应用的 `X-Application-Scope` 调用 `POST /applications/{app}/live-recordings`。正文包含 `recording_id` 和 `pages`。每个文档提交 `tab_id`、`document_id`、`binding_id`、`revision`。登记结果返回录制 ID 和文档数。同一录制、标签实例和文档重试可以重复登记，变更该文档的绑定会返回 409。新增或撤销授权后平台重新核对目录和规则版本。

持续模式单份接口正文默认 1 MiB，最高 32 MiB。建议为 32 MiB 正文配置 96 MiB 本地队列，并从单并发开始观察内存。响应体按解码后的字节数核算。结构复杂度、非 JSON 类型、浏览器缓存淘汰、队列满与超出字节预算分别留下状态。已配置的 MES API 保留业务 JSON 字段的原值；认证请求、凭据、Cookie 和未解析的原始消息不纳入持续采集。

### 持续录制中的提问与检索

持续模式的两个工具沿用原 identifier，输入契约新增 `live`。部署 API、tool-mcp 和 Runtime 后，按正常流程重新发布使用这两个工具的 Agent 和业务应用，使新 Job 冻结新契约。封存录制的既有请求格式继续有效。新旧契约哈希不同，在途 Job 按平台原有的工具快照规则处理。

浮窗 POST 消息时携带 `page`，包含绑定 ID、版本、顶层文档、提问毫秒数和用户时区。参与录制的页还带录制 ID 与标签实例，未录制时两项都传 null。重试复用同一消息键与整份输入。服务端从已授权的绑定版本推导环境、基地及车间路由。未选层级保留为空。跨录制查询同时匹配账号、应用、环境、基地、车间，空值也参与匹配。环境级记录只与同环境的环境级记录互查，基地级记录只与同一环境和基地的基地级记录互查。手工选择已封存录制时使用 `recording_id`。

| 调用 | 用途 |
|---|---|
| `search_recording({"live":{}})` | 本人本场当前标签，提问前 30 分钟。相同 URL 的两个标签独立。 |
| `search_recording({"live":{"scope":"recording","api_path":"/api/save"}})` | 本人同场且绑定范围完全相同，在同一窗口查保存接口。 |
| `search_recording({"live":{"scope":"today","http_status":422}})` | 本人、本应用、相同绑定范围，用户当地零时至提问时的多场录制。 |
| `search_recording({"live":{"request_key":"<命中的请求键>"}})` | 在当前范围查该请求、响应及正文。查其他页或历史时沿用原 scope。 |
| `get_recording_evidence({"live":{"reference":"<命中的引用>"}})` | 按本轮 Job 授权读取操作、基线或正文，后续请求继续带同一 reference 与返回的 cursor。 |

返回的 `event_id` 是逻辑事件身份，`observed_ms` 为页面观察时间，`source_seq` 为录制内序号。分页按接收顺序处理。时间线按观察时间及序号展示。即使当前已读完，也保留 `next_cursor`，同一筛选可以补读稍后传入的事件。调用者按事件 ID 去重。已登记但暂不可读的详情可通过 `pending_refs` 单独重试。跨筛选或跨 Job 的游标与引用会被拒绝。

| coverage | 回答应说明的范围 |
|---|---|
| `open` | 已送达窗口内的观察，插件可能还有未投递的材料。 |
| `page_not_recorded` | 提问时本页没有参与录制。 |
| `visible` | 此次返回的分片已在 Loki 读回，长度与摘要可核对。 |
| `partial` | 单次预算已用完，使用返回的游标读取后续分片。 |
| `missing_part`、`expired`、`unavailable` | 分别表示缺片、超出试用保留期和存储暂不可查询。缺少材料时只引用已核对的部分。 |

详情中的小对象直接以 JSON 返回。较大对象返回所取页的 UTF-8 摘录、按片序排列的 Base64、分片 SHA-256、对象总字节数及 SHA-256。取齐后按序连接字节，核对总长和总摘要。最大单正文为 32 MiB，每次工具回复限 256 KiB。授权失效时结束该次读取。

工单号或精密数量超出 JavaScript 可准确表示的范围时，持续采集按原 JSON 数字字面值写入分片。此类小对象通过 `value_json` 提供已过滤的精确 JSON 文本。

#### 从保存失败查到服务端

下面是合成答复样例。浏览器事件 ID 和日志中的关联标识分别保留。

| 观察 | 可给用户的答复 |
|---|---|
| C 的响应事件 E1 为 422，返回 BATCH_REQUIRED。已发布业务日志资源在相同 trace_id 下记录了批号校验失败。 | “C 页保存返回 422，响应要求补批号（E1）。配液基地服务的同一追踪记录也显示批号校验失败。” |
| A、C 调用同一接口。C 响应为 422，按其 request_id 在获授权资源的查询窗口内没有命中。 | “C 页的保存被接口拒绝（E1）。这个窗口没有查到对应后端日志，A 页的同名请求无法证明 C 的失败原因。” |
| 已查到浏览器和日志，现场尚未提供运行版本。 | “浏览器和日志都指向批号校验。还缺现场的 SVN 修订号，因此暂时无法确认具体代码分支。” |

例如响应提供追踪标识时，授权 Job 可调用 `query_loki({"environment":"qa","base":"plant","selector":{},"query":"<实际追踪标识>","minutes":15,"limit":20})`。环境与基地使用该 Job 对应的目录编码，时间窗须覆盖操作。业务资源自行注入固定选择条件。已知运行环境和数值 SVN 修订后，使用现有授权代码知识库核对该版本。
