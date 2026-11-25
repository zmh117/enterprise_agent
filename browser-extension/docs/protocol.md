# 内部消息、身份与本地数据

## 权限入口

控制消息仅接收 `sender.id === runtime.id` 且 `sender.url` 为本扩展 `control.html` 的发送方。内容脚本只能发送 `page.handshake`、`capture.batch` 和 transport error；没有任意 CDP、扩大 scope 或远程上传接口。

| 消息 | 关键字段与响应 |
| --- | --- |
| `scope.list` | 当前 profile 的窗口/标签目录、清理 URL、browserRunId |
| `session.start` | commandId、recordingId、browserRunId、rootBrowserTabIds、policy、environments（站点到环境编码） |
| `session.add_root` | commandId、recordingId、scopeVersion、browserTabId；新授权序号从本命令生效 |
| `session.mark` | commandId、recordingId、已纳入 browserTabId、note |
| `session.stop` | commandId、recordingId；同步关 gate，持久化后回复 |
| `session.status` | 会话、历史目标、通道、保存状态与缺口 |
| `page.handshake` | 真实 MessageSender 校验标签、frame、document、页面权限；返回文档票据或 null |
| `page.bound` | 隔离世界已设置自己的票据标记；后台再次核验发送方后刷新 CDP 映射 |
| `page.ended` | pagehide 结束当前文档票据；恢复需要重新握手及新录制流 |
| `capture.batch` | ticketId、packetId、index、total、UTF-8 有界 data 字符串 |
| `page.transport_error` | 已验证 ticketId 和错误代码；停止不完整流 |
| `export.create` | 对已终止会话排空已接受队列，允许控制页从扩展 IndexedDB 封包 |
| `history.list/delete` | 本地历史；只可删除终止会话 |
| `storage.retry` | 重试失败批次，并完成已经停止的会话 |

异步消息监听器返回字面量 `true`，用 `sendResponse` 回应。页面 nonce 只做通道匹配；MAIN world 和页面文本仍是不可信输入。票据不能通过 payload 的 tabId/documentId 自行授权。

## 生命周期与截止

后台顶层同步安装所有 Chrome 监听器。每次生命周期观察和授权命令使用同一个本地单调序号。候选关系保留约 30 秒，仅含创建/来源/关闭元数据。必须观察到创建序号在父谱系授权之后、在父关闭截止之前；跨 API 的时间戳只保存，不参与唯一授权判断。来源冲突、自循环、不确定创建边界不自动纳入。

目标关闭/全局停止先同步修改 `accepting`、`captureGeneration`、截止序号与观察时间。原票据、未重组 IPC、在途正文在接受入口失效；截止前已经接受的批次可以继续落盘。单独 debugger 中断只更新 network/runtime 的通道代数，不失效页面与语义。派生目标保留父历史引用，不依赖父继续打开。

一个根标签使用一个 root debugger attachment，专属 iframe/worker 使用 flat child session。共享 worker/service worker 内部不采集。页面源/请求 origin 都经策略过滤；无明确 frame 的消息不猜归属。独立网络重连使用新 UUID session key，请求键包含 recording、物理标签实例、session、requestId、redirectOrdinal。

页面通道须收到合法基线，语义通道须收到观察器已启动的确认，网络/错误通道须完成各自 enable。每个 PENDING 通道有 10 秒就绪期限；失败或超时为 LOST，晚到结果不能将其复活。页面通道失效时仍可接受有效的语义票据。子 CDP session 的失败记录其 session 缺口，不失效健康父 session 的 token。控制页只有四个必要通道都 ACTIVE 才显示目标完整就绪；截图始终独立显示停用。

开始按钮的权限请求结果不是整批启动的裁决。后台按已选根的实际授权分别启动；部分失败保留有效根，全部失效则保存 FAILED 会话及诊断。格式错误不创建会话。等待启动时收到 STOP 会撤销该 recordingId，重复 START 不恢复授权。

主机撤权通知先同步删除受影响的授权缓存，并使受影响标签的页面、语义、网络和错误代数失效，再等待 Chrome 权限查询和连接清理。影响范围同时检查根 URL、已登记文档和实际 CDP frame URL，覆盖网络已启用但页面票据尚未建立的子 frame。子 frame 撤权也重建该标签的 CDP 会话与父统一页面流，旧排队/在途正文不能使用父标签旧 token 继续提交；这会产生该标签短暂重建缺口，无关根保持原流。既有调试拒绝状态不会因重建而清除。

权限查询使用本次 recording 与查询代数构造完整快照，仅最新查询可原子替换缓存；迟到结果不能覆盖撤权后的新状态。连续撤权在同步截止后依次完成清理与对账，STOP、目标替换或新会话会使旧恢复工作失效。撤回模式仅用于判定哪些现有采集需要截止，不可作为授权依据；真正授权仍使用 Chrome `permissions.contains`。模式中的 scheme、主机边界和端口按 [Chrome 主机匹配规则](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns) 处理。

## rrweb、分片和语义

顶层使用 @rrweb/record 2.2.2 的统一流，同源子 frame 不重复启动 recorder，仅采语义；授权跨源 frame 启动 rrweb 协作实例。脚本通过 `scripting.executeScript` 在明确 document 中注入，不全站预录。每个新实例先接收 Meta + FullSnapshot 才允许 IncrementalSnapshot。跨源 attach 基线归入父流；未完全确认的节点/document 对应关系标 unknown。

页面侧先脱敏，隔离侧再按不超过 IPC 预算的 UTF-8 字符串片段发送。后台按发送方绑定的 ticket + packetId 重组，核验完整序号和 schema，再接受整个事件。重复片相同可重试、冲突片拒绝，队列/事件超限不截断 JSON。每个语义 `ui.action` 与其 `ui.state_snapshot` 同批提交，evidenceRefs 只指向实际保存事件。

2026-11-17 用户确认默认仅保护登录密码。策略版本为 `3.0.0`，普通输入与查询允许列表均为 `["*"]`，`maskAllText=false`、`sensitiveSelectors=[]`；普通文本、令牌、Cookie、Bearer/JWT 和业务属性原样保留。密码识别依据 type=password、密码 autocomplete、password/passwd/pwd/pass 等字段语义；Basic 认证保留用户名并掩码密码。用户另外配置敏感选择器时，其范围仍覆盖 target/state/context 和父容器汇总文本；无效选择器继续拒绝。包结构版本仍为 3.0.0，策略版本区分新旧采集语义，历史包不回填。

`DocumentRecord.baselineRef` 包含 eventId、承载的 recorderStreamId 和文档根 nodeId。顶层引用 FullSnapshot，子文档引用父统一流的 attach；语义专用流沿用该承载关系。后到的文档登记通过 `rrweb.document_mapping` 补充明确映射，保留原始事件。导航、frame 移除和录制重建关闭旧区间，旧基线仍可阅读，不会被新流覆盖。

rrweb 节点身份是 recorderStreamId + nodeId。MAIN world 根据真实 ownerDocument 或 iframe.contentWindow 观察关系，后台只接受同一目标中已经由真实发送方登记的文档票据。此映射用于解释不可信页面证据，不增加授权，也不证明页面未篡改内容。可确认的顶层/同源主体填写具体文档；无法确认的跨源节点保留 unknown/multiple 及原因。基线归属可以确认而个别跨源增量节点仍未知。

CDP frame 映射仅在本扩展 origin 的隔离执行上下文中读取票据标记，再与 MessageSender 登记核对；不执行网页 getter、不按 URL/兄弟顺序猜测。请求保留 chromeFrameId、documentId、frameMappingReason 和独立 cdpFrameId/loaderId。映射只对观测时的有效票据生效；早于绑定的请求为 null 和具体原因，不事后猜测。OOPIF 初始 URL 为空时只短暂读取 frame 元数据，授权确认前不启用业务域。相关平台模型见 [Chrome Debugger 文档](https://developer.chrome.com/docs/extensions/reference/api/debugger)。

请求的页面授权与上述文档身份绑定分别检查。已选目标内，以浏览器 CDP `requestWillBeSent.documentURL` 和非空 frameId 检查冻结页面策略及实际权限；它可早于 `frameNavigated`，因此新 iframe 的首次 Document 请求不再仅因缓存缺少 frame 而丢弃。documentURL 缺失时仅使用相同 loader 的已知 frame；不能拿 API URL/initiator 代替。Chrome document 关联仍要求隔离上下文验证且 loader 一致，新导航不借用旧文档。来源缺口分别为 `network_frame_missing`、`network_frame_unknown`、`network_frame_not_authorized`，只记录有界 ID、来源 origin 和资源类型，不保存被拒绝的正文或查询串。OOPIF 可在子 target 层更早以 `child_target_policy_excluded` 排除。

### 网络正文与额外头（2026-11-17 补充）

`text/plain` 可解析为 JSON 时按结构保护密码并保存 JSON 附件；其他自由文本以文本保存，仅处理明确标注的密码。普通值、令牌和业务字段不做通用脱敏。`application/json` 仅去掉精确的起始 XSSI `)]}'` 加 LF/CRLF 前缀后完整解析，不执行脚本或删除任意前导文本；其余非法 JSON 仍明确排除。无需密码替换的有效 JSON/表单保留原始格式；有密码时重新序列化，表单重复键保留。原 Content-Type 不改写。原始 UTF-8 和处理后附件分别受预算限制，不截断 JSON。旧通用 token 正则已移除，长连续文本不再引发该回溯阻塞。

压缩响应使用 `Network.dataReceived.dataLength` 累计解码后字节；超限为 `excluded_by_policy / decoded_body_size_limit`，附 `originalBytes`、`savedBytes=0`，不再安排正文读取。gzip Content-Length 是压缩大小，不当作解码大小。数据未充分观察时仍由读取结果的实际 UTF-8 字节进行预算校验；保存限额不代表 CDP 只读取前 N 字节。

读取失败原因区分 `inspector_cache_evicted`、`response_resource_unavailable`、`getResponseBody_failed`、`invalid_response_body_result`、`invalid_response_body_encoding`；不导出原始异常字符串，不重发现场请求。请求正文读取的异常结果为 `invalid_request_body_result`。排队任务在发送命令前和结果返回后均检查 requestId 当前 hop 与截止 token，避免重定向复用后读取或接受另一跳正文。Inspector 每资源缓冲为正文预算两倍，总缓冲至少 8 MiB 或正文预算四倍，按调试会话设置；每标签 BodyQueue 仍独立执行共享并发/字节预算，不保证浏览器永不淘汰。

ExtraInfo 状态：`not_expected` 表示协议明确不产生额外头（常见于 Service Worker）；`pending` 等待协议标志/双侧头；`matched_by_protocol_order` 表示已按 hop 顺序匹配双侧头；`unresolved_at_cutoff` 表示停止时仍无法完成匹配。未知标志构成顺序屏障；被页面/API 策略排除的跳保留空 hop 消费相应序号，避免后跳头串位，不保存该跳业务内容。

## IndexedDB 与恢复

问题包契约现为 `schemaVersion=3.0.0`：已覆盖文档必须带有效 baselineRef，已知节点/主体、语义快照和网络证据不得跨目标或文档串位。`shared/problem-package.schema.json` 是结构校验来源，构建期由锁定的 Ajv 生成静态函数，后台接受与包验证复用；引用关系由独立显式代码检查。扩展不在运行期编译 schema，不需要 eval、Function 或 CSP 放宽。

旧 1.0/2.0 开发样例不能用新校验器当作 3.0 包验收。3.0 将来源配置改为有限描述数组，并增加语义观察引用、省略信息、停止阶段和错误候选组。后台初始化时清理旧版本本地记录并重新采集，不做迁移；已导出的历史 ZIP 不修改。IndexedDB store 布局未变，数据库名称继续为 `mes-evidence-v1`，此名称不是问题包 schemaVersion。

数据库 `mes-evidence-v1` 属于扩展 origin。stores：recordings、targets、chunks、blobs、network、exports。chunks 含 stream、序号范围、SHA-256；同一事务写分片、正文/请求索引及 recording checkpoint。1 秒或约 256 KiB 触发，队列有界。保存异常关闭采集入口并展示错误，不报告虚假保存/导出成功。

`storage.session.browserRunId` 标记浏览器运行期，普通 service worker 唤醒不改变。后台异常重启时只恢复数据库已确认目标，旧代数失效，重新核对标签和权限，重建流基线，记录未提交批次可能缺失。浏览器重启/扩展重载清空 session storage 时，旧 recording 标记 INTERRUPTED，旧 tabId 不取得新授权。半途停止的会话仅整理已保存数据，不自动重录。

控制页关闭不影响后台。ZIP 生成/下载状态单独写 exports；取消下载或生成失败可重试，不删除本地唯一副本。没有自动上传、定时清理、跨 profile 联采或远程控制服务。

### P1：3.0 语义观察与范围预算（2026-11-16）

`before.status=observed` 只引用同一文档流此前已接受的 `ui.state_snapshot`，包含 `snapshotRef`、扩展 `observedAt` 和页面 `sourceTime`。没有此前观测或超出 512 条引用缓存时为 `unavailable`，不得把当前值回填为 before。程序 setter 在赋值前后各发一个观察；事件捕获、微任务、MutationObserver 和响应后快照分别保留 `phase` 与实际页面观察时间。动作及当前快照仍同批接受；消费方按引用读取以前状态。

关键动作只读最近的 form/dialog/显式 `data-evidence-region`，没有区域时只读目标。每区域最多 30 个字段、10 个提示、8,000 字符；目标最多 20 个 data 属性；单个文本/值最多 2,000 字符、文本 DOM 遍历最多 512 节点；全页初始/标记快照最多 150 个控件。`payload.omissions` 给出 scope、count、exact 与原因：`exact=false` 的 count 是省略下界，不是精确总数。省略会传播到 `quality.truncated/limitations`。这些预算不截断 JSON。

原生 dialog 的 open/close、角色弹框及祖先显隐、disabled/aria-busy、原生 invalid 校验和 value/checked/selectedIndex/option.selected 程序赋值均单独观察。STOP 对称恢复本采集器仍持有的 setter，断开观察器和监听器；业务代码后续替换的 setter 不被覆盖。

### P1：关联、错误和摘要契约

冻结策略 `correlationSources` 最多 32 条，字段限定为 frontendBuildId/backendBuildId/serviceInstance/requestId/traceId/spanId，来源限定 response_header、response_json、page_meta。`key` 分别为响应头名称、JSON Pointer、`meta[name="..."]`；`component` 区分组件，可选 origin/pathPrefix 进一步限定已经授权的观测。page_meta 仅在文档初始语义快照读取，不主动查询版本接口。响应 JSON 只读已经成功脱敏的完整正文。标准 traceparent 仍按已有 W3C 格式解析；不重发请求、不添加追踪头。

请求 `correlationFacts` 保存每个不同的字段/值/来源/组件组合及观察时间，requestKey 为来源；重复处理同一 ExtraInfo 不增加重复事实。页面元数据在 `ui.state_snapshot.after.metadataFacts` 中，以 eventId 为来源。recording.versions 是汇总投影，sources 保留首次入口，全部来源必须读取网络索引/状态事件。多值为 mixed_deployment；日志标识冲突时汇总为 null 并指向 correlationFacts，不能用 CDP requestId 替代服务端标识。

`sourceMappings` 最多 100 条，按 environmentId/component/buildId 匹配 codeSnapshot。唯一人工映射是 configured_unverified；缺失、多映射冲突或同组件混合构建为 unresolved。它不证明已经检索源码，recording.versions.codeSnapshotMatch 继续为 unresolved。摘要会展示具体映射判断与原始来源。

同一 debugger session + executionContextId + exceptionId + CDP timestamp 的重复异常传输不新增证据；仅保留最近 4,096 个稳定身份，淘汰后不再声称能去重。console/Log 没有稳定传输身份，不按文字去重。导出 errors/groups-*.ndjson 保存候选组，已知同目标/文档、精确消息/栈、2 秒内最多 64 个引用为一组；没有可靠文档身份时不合并。confirmed 永远 false，原始证据不删除；包校验重算候选组并比较引用。

摘要整体最多 28,000 字符，条目预览最多 700 字符，优先标记和异常，标记触发的状态优先于普通操作。各节报告总数、展示/省略数、范围和详情入口；不会把观测条数或候选组数说成已确认故障数。无需读取完整 rrweb 流。

### P1：标签正文预算与本地保存

同一 tabInstance 的 root/OOPIF/专属 worker 共用 BodyQueue。队列任务保留独立 session owner、token 与发送函数，等待最多 128 项，运行及等待项按 bodyBytes 上限预留并共享 queueBytes；并发为该标签合计 bodyConcurrency。子 session 截止只取消自己的等待项；旧 token 不复用，已在途结果返回后重新检查 gate。状态中的 bodyQueues 指标为计数及最坏正文预留字节，不是测量的 JS heap。

STOP 同步关闭所有 gate；另将 recordingId/reason/startedAt/finalState 写入 storage.local.stopIntent，同时开始连接清理与 Journal 排空。stopProgress 分别显示 cutoff/marker/cleanup/drain/terminal；5 秒期限从 STOP 开始，只产生等待诊断，不取消未确定事务、不重新采集、不宣称已保存。只有终结状态提交完成才显示保存成功。

Journal 保持一个写入链；失败后保留不可变批次、分片 ID 和事件身份，重试必须等待原事务已确定成功/失败。队列预算包括在途批次，metrics 的 inFlightBytes/queuedBytes 为接受记账字节。事务中止与配额失败关闭 gate；释放空间后用“重试保存”，不要删除唯一的会话副本或重复开始。事务已明确失败时可“导出已保存部分”：只读已提交的 IndexedDB 前缀，导出副本标 INTERRUPTED/saved_prefix_only，原 Journal 和失败批次不变；导出状态写入失败不阻塞该只读救援路径。未确定结果的挂起事务不启用此入口。

停止整理时后台中断，恢复读取 STOP 意图，只整理已提交证据并标记 interrupted_finalization，不重新打开采集；未提交的内存尾批无法跨进程保证，必须报告缺口。普通活动恢复仍建立新流和新基线。拒绝的新事件不占用已保存流序号；正文触发硬预算截止时，终结请求只采用此前已接受快照，禁止保存未接受 bodyRef。未完成分片直接丢弃并记录缺口，不拼成截断 JSON。

每个 CDP collector 最多保留 5,000 条请求链，超过后新链不保存并提示结束后新建会话；这是独立于会话字节预算的覆盖限制。默认 200 MiB 是接受记账预算（含索引更新），不等于压缩 ZIP 或物理磁盘字节。600 MiB ZIP/700 MiB 解压只是校验防护阈值，并非已验收的容量承诺。

## 第 7 组生命周期与导出补充

正式 replacement 同时可能由 tabs 与 webNavigation 通知；旧实例在 await 前占用替换资格，返回后再次核对身份，保证只登记一个新实例。异步 attach 期间发生导航/丢弃恢复时，按 tabInstanceId 合并一次后续启动检查，避免错过新文档注入；截止后不补注入。

导出尝试使用独立 attemptId（exports store 的 id），保留 recordingId、startedAt、observedAt、generating/downloading/complete/download_interrupted/failed。控制页重开查询下载结果，不能将未确认生成或下载当成完成；证据 stores 不因导出失败、取消或关闭而删除。
