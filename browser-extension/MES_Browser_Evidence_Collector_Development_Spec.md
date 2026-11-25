# MES 浏览器问题采集插件：开发规格（单浏览器版）

> 文档版本：1.0.0  
> 编写日期：2026-11-16（Asia/Shanghai）  
> 交付对象：负责实现的开发 Agent 与人工评审者  
> 目标产物：单浏览器 Chrome 扩展、结构化问题证据包  
> 文档性质：可实施的产品要求、技术设计、边界约定与验收标准。本文中的预算、状态和协议属于本项目设计，不是浏览器平台的原生保证。

## 0. 给开发 Agent 的执行说明

请按本文实现一个通用浏览器采集助手。人员手动选择采集目标、开始采集、操作 MES、添加时间标记、结束采集；产物交给已有 Agent，联合对应版本的源码和后台日志分析原因。

开发时先检查现有仓库、AGENTS.md 和依赖，复用可用实现。本文没有提供真实 MES 地址、接口成功码或服务器版本接口；这些必须做成配置或适配接口，演示环境使用本地测试服务，不能编造已接入生产系统。文件服务上传为可选项，有现成接口时再适配。

以下为本期需求及本文采用的技术约定，实施时不得静默缩小采集要求：

1. 本期只采集一个 Chrome 用户配置（profile）中的标签；开始前可从该配置的多个窗口选择多个根标签。
2. 选中标签后续新建的子标签自动加入；子标签继续派生的标签递归加入。
3. 关闭某个标签后，停止该标签的页面、交互、接口、错误等所有新采集；保留关闭前已经采集的数据。
4. 父标签关闭不停止仍然存活的子孙标签。
5. 用户手动结束整个会话时，本次全部根标签及后代均停止新采集。
6. 技术方案采用 rrweb 录制端提供通用页面采集，同时增加业务语义摘要；不依赖播放器。
7. 本期不建设页面回放播放器、自动重跑、接口重发、自动修改 MES 或自动提交生产业务。
8. 问题包以 Agent 分析为目标，必须能关联具体操作、页面状态、请求、日志线索、部署版本和源码快照。
9. 安装插件后即可本地录制、保存和导出；不要求启动协调服务、本地守护进程或新的后端平台。

**实施原则：先验证采集范围和停止边界，再扩大采集内容；以真实浏览器验证为准，不能把 API 调用成功等同于证据完整。**

## 1. 背景、目标与范围

### 1.1 业务背景

现场实施提交 MES 工单时，经常缺少准确的操作步骤、字段值、页面状态、请求参数与错误信息。目标是减少人员手工整理材料的负担，形成可检索、可引用的证据，辅助 Agent 联合源码与后台日志定位原因。

### 1.2 产品目标

- 能解释“在哪个现场、哪个页面、哪个业务对象上，进行了什么操作”。
- 能展示关键操作前后页面字段与状态变化。
- 能获取采集期间受支持目标内可取得的接口请求、响应和错误信息。
- 能追踪多个根标签及其递归派生关系。
- 能准确停止已关闭标签的采集，并防止异步回调越过截止边界。
- 能在扩展本地暂存和导出；问题包可交给已有 Agent 使用。
- 能向 Agent 明确说明证据的范围、版本、脱敏、截断及缺失情况。

### 1.3 本期交付边界

| 能力 | 本期要求 |
| --- | --- |
| 手动开始、添加时间标记、手动结束 | 必须 |
| 多窗口、多根标签选择 | 必须 |
| 派生标签递归自动加入 | 必须，在浏览器提供可靠来源证据和目标权限允许的范围内 |
| 关闭标签即停止该标签新采集 | 必须 |
| rrweb 页面采集、操作语义、网络与错误 | 必须 |
| 本地 IndexedDB、问题包导出 | 必须 |
| 多个 Chrome 配置、独立浏览器联合采集 | 本期不实现 |
| Edge、Firefox、Safari、手机浏览器 | 本期不承诺 |
| 后台日志查询、源码检索与根因分析 | 由后续 Agent 完成；本项目提供证据与消费契约 |
| 文件服务上传 | 可选适配；本地录制和导出不能依赖上传服务 |
| 视频录制、播放器、自动重跑 | 本期不实现 |
| 新建代码知识库、日志平台、知识图谱 | 不属于本项目交付 |

## 2. 名词与浏览器能力边界

### 2.1 统一名词

| 名词 | 定义 |
| --- | --- |
| 采集会话 recording | 一次用户开始至结束的本地采集任务，可含多个根标签和后代 |
| 浏览器范围 | 当前扩展所在的一个 Chrome 用户配置；其他配置中的标签不在本期范围内 |
| 浏览器运行期 browserRunId | 当前浏览器运行时期的 UUID；普通扩展后台唤醒不能更换 |
| 窗口 window | 当前配置中的浏览器窗口，用于分组展示和批量选择 |
| 根标签 root tab | 用户明确选择的标签 |
| 派生标签 descendant | 父谱系取得本次采集资格后新创建、且来源与创建资格可验证的标签 |
| 纳入集合 enrolled set | 根标签与符合规则的递归后代；与当前是否有可用采集通道分开维护 |
| 文档 document | 标签/iframe 某次加载的页面文档；完整导航和 SPA 路由变化应区分 |
| rrweb 流 recorder stream | 一次 recorder 实例输出的、有基线和顺序依赖的事件序列 |
| 覆盖缺口 coverage gap | 未采集、不可采集、采集延迟、丢失或截断的一段证据范围 |

### 2.2 单浏览器的准确范围

同一 Chrome 用户配置的多个窗口可以由当前扩展管理。不同 Chrome profile、不同用户数据目录的独立实例不在本期范围内；单个扩展不能枚举任意其他配置。浏览器窗口 API 和 Chromium 的 profile 过滤实现支持这一边界。[S1][S2][S3]

产品选择器采用“窗口 → 标签”的层级：

- 展示当前配置中的窗口与标签，不建设浏览器目录、配对或联采控制。
- 同一 Chrome 的多个 renderer 进程不改变本期单浏览器范围。
- 同时只允许一个活动 recording；一次 recording 可以包含多个窗口中的多个标签。
- 本期隐身模式显式不支持；不混用普通模式与隐身模式的身份和存储。
- Chrome 内置页面、扩展管理页、浏览器商店等受限页面显示“不可采集”，不绕过限制。

**建议技术基线：Chrome 125+，并在交付时记录实际验收的稳定版版本。** 选择 125 是为了使用 debugger flat child session 等能力，属于兼容基线，不代表推荐运行过旧的浏览器。[S5]

## 3. 用户流程与界面

### 3.1 开始面板

展示：

- 按站点关联当前系统账号可用的环境。历史记录以时间、环境和记录编号识别。
- 现场环境名称/标识。
- 当前 Chrome 版本、插件版本、是否已有活动会话。
- 窗口下的标签标题、经过清理的 URL、可采集状态。
- 复选框，可选择多个窗口中的多个标签。
- 采集策略摘要：允许的页面域名、API 规则、脱敏策略、容量限制。
- 明确提示“会自动纳入这些标签后续新开的子标签”。

勾选整个窗口或“全选”，是批量选择当前列出的标签；点击开始时展开并冻结为明确的 rootTabInstances，不代表这些窗口此后任意新标签都自动纳入。

URL 选择信息默认隐藏查询参数值和 fragment 中可能存在的令牌。目录元数据仅为用户选择服务，不应作为所有浏览页面的长期历史上传。

### 3.2 启动

1. 校验至少一个有效根标签；校验 browserRunId、标签是否仍存在、权限和本地会话空闲状态。
2. 建立会话及根集合，先注册生命周期监听，再并行启动各目标通道。
3. “准备中”阶段产生的可确认后代也要登记，不能等所有根就绪才开始观察派生关系。
4. 页面、网络、错误通道分别报告成功/失败及实际覆盖起点。
5. 至少一个目标通道成功后可进入“采集中”；部分目标失败时显示“部分采集”，列明失败原因。
6. 全部目标失败时结束准备并保留诊断信息，不能显示正在采集。
7. 启动只 attach、注入和读取，不刷新 MES、不重放业务请求、不主动提交表单。

### 3.3 采集中

持续显示：

- 会话编号与已采集时长。
- 正在采集、部分采集、等待权限、已关闭的标签数量。
- 根/子/孙关系以及每个标签的页面、网络、错误通道状态。
- 本地数据量、保存状态、明显缺口；配置了上传功能时才展示上传状态。
- “添加时间标记”“添加标签”“结束采集”入口。
- 工具栏徽标/状态提示。关闭插件弹窗不结束采集。

允许用户手动添加一个标签，作为新的明确根节点；新增来源记为 manual_add。该入口也用于浏览器无法提供可靠谱系的场景。第一版不必实现复杂的运行中批量排除规则。

“添加时间标记”绑定当前已纳入标签；当前标签不在集合内时提示先添加，不自动扩大范围。

### 3.4 结束与交付

- 结束采集后可直接预览并导出。
- 先停止新采集，再整理已经接受的数据；停止与压缩/上传显示为不同进度。
- 展示根与后代、采集缺口、请求数量、错误摘要。
- 必须可本地导出 ZIP 问题包；上传为独立的可选适配。
- 脱敏预览可查看摘要、选定请求和关键截图；不需要播放器。
- 所有目标已关闭时显示“当前无活动标签，等待结束/导出”，不得自动选取新标签继续录制。

## 4. 范围规则：根标签与递归派生关系

以下为本项目的规范规则，不是通过 URL 推断的启发式规则。

### 4.1 必须满足的不变量

- INV-01：只有根标签、手动添加标签或来源已确认的后代，才可产生业务证据。
- INV-02：未纳入标签不得 attach debugger、启动 rrweb、读取表单值或读取/保存网络正文。
- INV-03：同一个标签在一个会话只启动一套相应采集器；重复事件必须幂等。
- INV-04：派生标签按关系递归加入，不能仅支持根的一层直接子页。
- INV-05：父关闭只停止父；存活后代不依赖父对象存活。
- INV-06：窗口移动、标签排序、前后台切换不改变已纳入关系。
- INV-07：关闭/停止后，不允许任何旧异步任务重新激活目标或接受新业务证据。
- INV-08：采集缺口必须可见，不能把未采到解释为没有发生。
- INV-09：数据来源必须由扩展实际路由确定，页面 payload 不能自行声明另一个 tabId 取得授权。
- INV-10：结束前已采集的证据可以继续落盘/上传，不能因标签关闭删除历史。

### 4.2 自动纳入与不自动纳入

| 情况 | 行为 |
| --- | --- |
| 已纳入 A 新建 B，B 新建 C | 自动纳入 B、C，保存 A→B→C |
| 后代在新窗口中打开 | 纳入后代；新窗口其他原有标签不纳入 |
| 目标从窗口 1 拖到窗口 2 | 继续采集，仅更新 windowId |
| 两个未选标签打开与 A 相同的 MES 地址 | 不纳入 |
| 用户 Ctrl+T 后粘贴相同 URL | 不纳入，除非手动添加 |
| 会话开始前，或手动添加根之前已经存在的“旧子页” | 必须明确选择，不因后来纳入父页而追溯纳入 |
| 用户复制/恢复标签 | 仅在可信新建来源证据满足规则时纳入；否则手动添加 |
| window.open 复用一个未选的已有命名窗口 | 未创建新标签，不按“新后代”自动纳入 |
| 弹窗被浏览器拦截 | 没有实际新标签，记录可得提示，不伪造后代 |
| 标签跳转到另一个允许页面 | 保留标签成员身份，按新 document 重建采集 |
| 标签跳到未获权限/规则禁止的页面 | 保留谱系，暂停相应通道并展示原因；返回允许页面后建立新片段 |
| 通过系统在其他 profile/浏览器打开目标 | 本期范围外，不能通过当前插件加入；不根据 URL 猜测亲缘 |

自动扩展的两个条件须同时满足：

1. 属于本次会话明确授权的根/后代谱系。
2. 所在文档、frame、请求满足能力、权限和采集策略。

### 4.3 来源证据

至少组合使用：

- `chrome.tabs.onCreated` 提供的 `openerTabId`。
- `chrome.webNavigation.onCreatedNavigationTarget` 的 `sourceTabId → tabId`，保留 sourceFrameId。

openerTabId 可能缺失，且只在 opener 仍存在时可返回，因此必须尽早保存已确认谱系。onCreatedNavigationTarget 提供新导航目标的来源，但不能承诺任意浏览器版本、任意打开方式都无遗漏。[S1][S4]

禁止用以下内容单独证明派生关系：相同 URL、域名、Referer、window.opener、最近激活标签、标签排列位置、相近创建时间。

`noopener` / `noreferrer` 会影响页面可见的 opener/Referer；并不意味着浏览器的导航来源事件一定缺失。普通新标签、Ctrl/Cmd+点击、中键、右键新窗口、window.open、noopener、noreferrer 均须实际验证。[S17]

### 4.4 去重、乱序与父页快速关闭

- 生命周期事件监听必须在任何 attach 前就位。
- 在内存维护短期候选关系，例如默认 30 秒，只保留 ID、来源、时间、事件类型等最小元数据。
- 初始根的资格从本端 session.start 生效时开始；手动新增根从本端 session.add_root 生效时开始。保存 scopeGrantedAt、授权命令及来源时钟/顺序依据。
- 父被纳入时，可以递归检查候选关系以解决通知乱序，但必须证明子页是在父谱系取得本次资格之后新建；候选缓存不能用于追溯扩大授权。
- 后代资格沿可信创建关系递归继承，不简单等于通知到达时间。例如 B 的来源通知延迟，但可证明 B 在 A 授权后创建，且 C 随后由 B 创建，则 B/C 可递归纳入。
- 未选 A 先创建 B，随后用户手动加入 A：B 不自动加入；A 在本次授权后新建的 C 可以加入。
- 父关闭后保留历史节点；有可信证据证明子页是在有效跟踪期间新建时仍可纳入。
- 时间只辅助判断，不能将不同 API 的时钟直接比较后当作唯一授权依据。
- 跨越会话开始/结束边界且无法确定资格的目标，不自动采集；提示手动添加。
- 同一子页的重复来源通知合并；冲突/循环关系保留诊断并标记歧义，不扩大范围。
- 来源确认后立即启动采集；URL 暂为空/about:blank 时保留待就绪记录，等待可采集文档。

## 5. 标签关闭、全局停止与状态机

### 5.1 关闭截止的精确定义

“关闭即停止”以扩展后台观察到明确关闭事件并处理关闭标记的时刻为技术截止点。浏览器事件投递并非物理零延迟，不能声称在用户按关闭按钮的同一 CPU 时刻完成所有处理。

处理顺序必须是：

1. 同步将该 tabInstance 标记为停止接受新业务数据，增加 captureGeneration，记录 cutoffObservedAt/stopReason。
2. 停止为它安排任何新的页面读取、注入、网络正文读取、截图和语义采集。
3. 清理该标签的 recorder、监听、专属 CDP 子 session 和目标映射；已关闭 target 的 detach 失败按已释放处理。
4. 允许截止前已经通过接受入口、进入本地队列的数据完成持久化和上传。
5. 截止后才返回的 CDP 正文读取结果、页面消息和截图结果均丢弃业务 payload，仅增加迟到计数/终止诊断。
6. 未完成请求标记为 incomplete_target_closed，保留已有方法、参数、已收到状态等；不得补造 HTTP 错误或空正文。
7. 保留历史谱系和已采数据；不递归停止存活子孙。

**不采用“标签关闭后等待所有网络请求完成再停止”的实现。** 页面关闭不证明后台事务已经取消，Agent 必须将其解释为浏览器侧证据不完整。

全局手动停止采用相同的严格接受规则。结束前排队的数据可以继续保存；不是所有在结束前发起、结束后才返回的内容都自动允许追加。若将来需要宽松尾包策略，必须作为单独产品变更。

控制/诊断事件（tab_closed、stop_ack、incomplete_finalization、late_result_dropped 等）可以在截止后写入；它们不包含新获取的页面/接口业务内容。

### 5.2 状态分层

不要把“标签存在性×所有通道组合”做成巨大的枚举。

会话状态（全部在当前扩展内管理）：

| 状态 | 含义 |
| --- | --- |
| DRAFT | 用户选择目标 |
| STARTING | 根集合已建立，通道启动中 |
| RECORDING | 已开始且未手动结束；活动目标可降为 0，通道质量另行记录 |
| STOPPING | 全部目标的新业务接受入口已同步关闭，正在清理采集器 |
| FINALIZING | 整理截止前已接受的数据，进行持久化与问题包检查 |
| READY | 产物可导出；证据可为 complete 或 partial |
| INTERRUPTED | 浏览器退出等导致异常结束，已有数据可整理 |
| FAILED | 无法开始，记录明确原因 |

“已停止采集”“正在保存”“正在生成 ZIP”分别展示。STOPPING 期间入口已经关闭，清理任务失败不能使旧任务重新进入；ZIP 生成失败可对已保存数据重试，不重新录制页面。

每标签维护：

- lifecycle：OPEN / REPLACED / CLOSED。
- captureState：PENDING / ATTACHING / ACTIVE / DEGRADED / BLOCKED / STOPPED。
- channels：page、semantic、network、runtime、screenshot 各自的状态、起止时间、缺口。
- quality：complete_within_declared_scope / partial / unavailable。
- stopReason：tab_closed、session_stopped、browser_exit、policy_blocked、quota_exceeded 等。
- captureGeneration：标签级失效代数；关闭、替换、全局停止等使该标签所有通道失效时递增。
- channelGeneration：每个通道独立的失效代数；单一网络/页面通道中断只使该通道旧任务失效，不误停仍可用的其他通道。

“没有活动标签”是计数推导出的展示状态，不自动等于会话已结束。

### 5.3 生命周期处理表

| 事件 | 处理 |
| --- | --- |
| tabs.onRemoved | 关闭该标签；窗口整体关闭也逐标签执行 |
| tabs.onDetached / onAttached | 窗口迁移，更新 windowId，保持采集 |
| tabs.onMoved | 同窗口排序，更新展示即可 |
| tabs.onReplaced | 浏览器明确替换；旧实例停止，新实例继承纳入资格，记录 replacesTabInstanceId |
| webNavigation.onTabReplaced | 与 tabs.onReplaced 合并去重 |
| debugger.onDetach | 区分 target_closed 与用户取消/调试冲突；标签仍在时只标记相应通道降级 |
| 页面完整导航/刷新 | 标签不变，新 document/recorder 片段，旧事件归旧文档 |
| SPA history/hash 变化 | 记录路由和上下文，不仅凭 URL 变化生成新 document |
| BFCache 恢复 | 检查原文档和 recorder 是否可继续；新建流则必须重新建立基线 |
| tab discard/freeze/crash | 保存缺口；恢复后重新核对通道，不能伪造持续正常 |
| 普通 Service Worker 重启 | 在同 browserRunId 恢复已确认会话，重新对账，防重复注入 |
| 浏览器重启/扩展重载 | 新 browserRunId，旧会话标中断；不凭复用 tabId 自动继续 |
| 全部标签关闭 | 当前采集数为 0，等待结束/导出；无关新标签不加入 |

tabs.onDetached 与 debugger.onDetach 名字相似但含义不同，必须分别实现。[S1][S5]

### 5.4 异步任务防越界伪代码

以下是行为示意，允许采用等效实现：

```typescript
async function readResponseBody(context: CaptureContext, request: RequestRef) {
  const ticket = captureGate.issueTicket(context);
  if (!ticket) return;

  const result = await cdp.getResponseBody(request);

  // ticket 同时绑定会话、浏览器运行期、标签与通道代数。
  // 关闭、停止、替换或对应通道失效均使 ticket 失效。
  if (!captureGate.isStillValid(ticket)) {
    noteLateResultWithoutPayload(request.key);
    return;
  }

  const sanitized = redactAndBound(result, context.policy);
  // 接受检查与进入已接受队列必须处于同一串行临界区。
  captureGate.acceptOrDrop(ticket, sanitized);
}

function stopTab(tabInstanceId: string, reason: StopReason) {
  // 先关闭入口，后做异步清理。
  captureGate.close(tabInstanceId, reason);
  markUnfinishedRequests(tabInstanceId, reason);
  scheduleCollectorCleanup(tabInstanceId);
  flushAlreadyAcceptedRecords(tabInstanceId);
}
```

stop、close、detach 的重复到达应幂等；正常丢弃迟到业务 payload 不能让终止状态回到 ACTIVE。

issueTicket、isStillValid、acceptOrDrop 都必须检查会话状态、browserRunId、当前授权、captureGeneration 和所属通道的 channelGeneration。网络调试断开只递增网络/runtime 等实际失效通道的代数；仍存活的页面/语义采集器继续通过自己的合法票据提交。

scopeVersion 表示授权集合修订；手动增加其他根标签不应使原有存活标签的全部采集器失效。接受入口根据当前成员资格与对应代数核验，不能简单把任意版本变化当作全局停止。

## 6. 启动覆盖、权限与采集隔离

### 6.1 新标签首批请求的客观边界

新标签发现、来源确认、debugger attach、Network.enable、脚本注入均为异步。首个页面请求或最早的 Fetch/XHR 可能发生在通道就绪前。webNavigation 与网络事件也没有固定先后屏障。[S4][S5]

必须保留：

- createdObservedAt / lineageConfirmedAt。
- networkReadyAt / runtimeReadyAt。
- recorderStartedAt / firstBaselineAt。
- possibleInitialGap 及具体 gap 信息。
- 录制开始前已存在请求/连接的覆盖限制。

降低延迟靠监听器提前注册、来源确认后尽快附加、按 document 尽早注入。不得通过录全浏览器后再筛选、自动刷新、重发业务接口、禁用缓存、暂停页面等方式隐藏缺口。

### 6.2 权限建议

Manifest V3，优先使用下列明确权限：

| 权限/能力 | 用途 |
| --- | --- |
| tabs | 选择目录和生命周期所需的标题/URL等信息；不是读取所有页面业务内容的授权 |
| webNavigation | 导航、新目标来源、document/frame 变化 |
| scripting | 在明确纳入的目标注入采集器 |
| debugger | 选定目标的 CDP 网络与错误证据 |
| storage | 扩展设置、运行期信息和会话控制 |
| downloads | 导出问题包时使用 |
| optional_host_permissions | 用户选择/部署配置的业务域名；跨源 frame 需要相应权限 |
| unlimitedStorage | 只有容量验收证明需要时再申请，仍设置应用自身预算 |

activeTab 的临时授权不能替代多标签和后续派生页面需要的访问权限。[S1][S6]

默认允许域名由选择的业务站点及用户配置组成；派生到未获权限的域名时展示等待权限/未覆盖，不能绕过权限。接口域名可与页面域名不同，API 允许列表单独配置。

### 6.3 未选标签的处理

可以监听必要的全局 tabs/webNavigation 生命周期元数据，用来确定谱系和展示选择器。禁止启动未选目标的业务采集。

如使用预注册 document_start bootstrap：

- 它只能在允许域名中检查自身是否已获会话授权。
- 在后台确认之前不启动 rrweb，不提取字段、文本、截图、console、网络正文。
- 收到授权后仍再次校验 document、scopeVersion 与 captureGeneration。
- 不允许页面通过伪造消息改变根集合。

### 6.4 后台标签与截图

- 已纳入标签在后台仍应尽可能采集 DOM/网络；记录 visibility/focus 状态以解释浏览器节流。
- 不为获取截图而偷偷切换或激活标签。
- 截图默认在人工添加时间标记时生成；本期仅使用绑定指定 CDP target 的 Page.captureScreenshot，并验证该 target 与目标标签实例的映射。[S5][S21]
- 不回退到 tabs.captureVisibleTab：它按窗口当前活动标签截图，前后检查活动标签仍存在切换竞态，不能满足本项目不采未选标签的隔离要求。[S1]
- 无法取得正确截图时记录 unavailable，不影响其他证据。
- 启动 debugger 通常存在浏览器提示/调试冲突；用户取消后不无限重试抢回连接。

## 7. rrweb 与业务语义采集

### 7.1 使用方式

- 使用独立录制包（例如经验证版本的 @rrweb/record），锁定版本并随扩展打包。
- 不依赖运行时 CDN，不引入播放器作为运行依赖，不接入外部 rrweb Cloud。
- emit 事件进入统一采集入口，脱敏、分片、保存。
- stop 函数、observer、事件监听、消息通道的生命周期由标签/document 管理器拥有。
- rrweb 是通用页面证据来源，语义信息与日志/源码关联由项目自身补充。[S7]

### 7.2 基线、顺序与节点引用

每个新顶层 document、每次新 recorder 实例，必须有完整基线（通常为 Meta + FullSnapshot）。后续增量必须能归属到对应基线，不能任意丢掉依赖事件后仍宣称完整。[S8]

元素引用至少包含：

`recorderStreamId + rrwebNodeId`

同时携带 tabInstanceId、documentId（可确认时）以及必要的 frame 映射。不同流中的 nodeId=42 不是同一个元素。

完整导航时建立新 document；SPA 路由变化按实际文档身份记录。rrweb 流重启时更换 recorderStreamId，不复用旧流的节点编号语义。

### 7.3 iframe 录制策略

默认优先验证 rrweb 顶层统一流：

- 顶层 recorder 负责其可观察的同源 iframe。
- 对获得权限的跨源 iframe，按 rrweb 的父/子协作方式接入。
- 每个被覆盖 iframe document 都必须有完整基线及 frame/document 映射。
- 在统一流中，子文档基线可能存在于 iframe attach 增量中，不要求每个子 frame 都独立产生 FullSnapshot。
- 不允许同时由父 recorder 递归录制同源 iframe、又在同源 iframe 建独立 recorder，导致双份同等证据。
- recordCrossOriginIframes=false 不等于禁用同源 iframe 递归。
- 如果采用每 document 独立流，必须验证如何关闭父对子文档重复观察后才能切换架构，不能未经验证改库。
- 权限不足、不可注入、Shadow DOM/Canvas 等未覆盖内容进入 capabilities/gaps。[S9]

统一流必须区分消息发送文档与实际被观察文档：emitterContext 保存经扩展确认的发送方；subjectContext 保存变化所属文档/frame。顶层转发 iframe 变化时，不能把顶层 MessageSender 的 documentId 填成子页变化的来源。使用节点所属文档、iframe attach 基线和已验证映射确定 subjectContext；无法确认则写 unknown/null 及原因。跨多个文档的事件保留节点到文档的映射，不强行声明整个事件只属于一个子文档。

### 7.4 执行世界与通信

需要监听页面程序赋值、原生 setter 等行为的 rrweb 代码，优先在经过验证的 MAIN world 中运行；扩展权限与消息路由留在隔离侧。不能仅在默认 ISOLATED world 覆盖 window.fetch/输入 setter，就假定能够观察页面自己的调用。[S6][S10]

启动成功需验证实际收到基线、普通输入、程序赋值和动态弹框事件。重复 START 必须返回已有状态，不重复挂监听。

页面消息按不可信输入处理：

- 使用扩展已知注入目标和真实 MessageSender 确定授权标签及 emitterContext；subjectContext 按第 7.3 节另行映射，不能直接用发送方替代。
- 校验 schema、长度、来源上下文、会话和 generation。
- nonce 只用于通道匹配，不能证明页面数据不可伪造。
- 页面桥只能送采集数据，不能触发任意 debugger 命令、改变范围或上传到任意 URL。

### 7.5 业务语义事件

使用固定规则生成，不需要在浏览器中调用 LLM。

至少记录：

- action：click、input/change、select、submit、dialog_open/close、route_change。
- target：role、label、可见文字、字段 name、业务 data-* 标识、稳定 ID。
- state：value、checked、selectedOptions、disabled、readonly、可见性、校验提示、loading。
- context：模块、表单/弹框名、工单/批次/配方/控件 ID 和版本（能够合法读取时）。
- before/after：known、masked、unavailable 等状态和值。
- evidenceRefs：支撑该摘要的原始事件 ID。

evidenceRefs 只能引用已经接受且最终包含于问题包的原始观测。直接读取控件的前后状态应保存为 ui.state_snapshot；语义变化可以引用这些快照，不要求所有语义都引用 rrweb。原始观测与摘要应同批接受并在事务中提交，或先确认观测已接受再生成摘要。停止时若尚未重组完成的 rrweb 大事件被丢弃，不得让已有语义留下指向该事件的假引用；缺失依据应明确标记，并在导出时检查引用闭包。

只保存点击之后的最终 DOM 会漏掉短暂 toast。应持续观察重要文本、节点和属性变化，同时在开始、关键动作前后、关键响应后及添加时间标记时读取相关区域状态。

MutationObserver 与 input/change 不能覆盖所有程序赋值；关键时刻要补读实际属性。异步页面更新要按实际观察时间追加，不把固定延时后的状态当作操作瞬间状态。[S11][S12]

语义采集以相关表单、弹框、提示区为范围，避免每次鼠标移动遍历整页。根因推断放在后续 Agent 中。

## 8. 网络、错误与专属 target 采集

### 8.1 推荐通道

对纳入的标签使用 chrome.debugger/CDP：

- Network.enable。
- Runtime.enable。
- Log.enable。
- 按实际需要启用 Page 事件、截图能力。
- 对能明确归属该标签的 iframe/dedicated worker 处理子 session。

chrome.debugger 支持这些调试域，但不意味着获得所有浏览器内部信息。[S5]

### 8.2 请求生命周期

| CDP 事件/命令 | 处理要求 |
| --- | --- |
| Network.requestWillBeSent | 保存方法、URL、参数、请求类型、时间、initiator、frame/loader信息、可得请求体 |
| Network.requestWillBeSentExtraInfo | 按本 session 的 requestId、重定向链和 ExtraInfo 队列归属具体跳；不假定与主事件严格有序 |
| Network.responseReceived | 保存 HTTP 状态、响应头、MIME、缓存/SW来源等信息 |
| Network.responseReceivedExtraInfo | 结合 hasExtraInfo / redirectHasExtraInfo 等协议线索归属具体跳；不能只按 requestId 覆盖当前跳 |
| Network.loadingFinished | 在范围仍有效且策略允许时，尽早读取正文 |
| Network.getResponseBody | 处理 base64Encoded、大小、编码、脱敏和截止检查 |
| Network.getRequestPostData | 必要时取请求体；不能保证 multipart 文件内容完整 |
| Network.loadingFailed | 保存真实网络失败/取消原因；HTTP 失败与网络失败分开 |
| Network.webSocketFrameSent/Received | 如业务使用，采集有界文本消息；二进制默认只留元数据 |
| Network.eventSourceMessageReceived | 如业务使用，保存有界 SSE 消息及连接归属 |

正文不可拖到会话结束才统一读取。CDP 正文缓冲/可用性存在限制；取不到必须记录原因。[S13]

### 8.3 网络标识与结果

请求键至少包含：

`recordingId + tabInstanceId + debuggerSessionKey + cdpRequestId + redirectOrdinal`

重定向可能复用请求标识，不能覆盖前一跳。浏览器 CDP frameId 是协议中的标识，Chrome 扩展 frameId 是另一套标识，应分字段保存并建立可验证映射，不直接混用。

ExtraInfo 可能早于或晚于对应主事件。实现需维护每个 debugger session 内的请求链与待匹配队列，结合协议标志确定 redirectOrdinal；无法唯一匹配时保存待匹配/歧义诊断，不得把前一跳头信息并入后一跳。[S13]

区分：

- networkOutcome：finished / failed / incomplete。
- httpStatus：收到则保存，未收到为 unknown。
- businessOutcome：success / failure / unknown，依据配置的 MES 响应协议判断。
- request.bodyCaptureStatus / response.bodyCaptureStatus：见第 10 节，路径必须统一。

HTTP 200 不能直接判业务成功；不对所有接口硬编码 code != 0 为失败。

### 8.4 请求归属与跨标签隔离

- 根标签和派生标签分别 attach 并保持独立归属。
- Target.setAutoAttach 用于相关 iframe/worker，不代替 tabs/webNavigation 的新标签发现。
- 子 target 建立 session 后也要启用所需域；递归处理关联 target 的范围，不能假设 auto-attach 自动覆盖所有深度。
- 默认 waitForDebuggerOnStart=false，不暂停 MES。
- 共享 worker/service worker 可能服务多个标签：无法准确归属的内部流量不全量采集，记录覆盖限制。
- tab 关闭后释放该 tab 专属 target，停止其所有通道；不能因为 worker 还存活继续把它的消息记到已关闭标签。
- 页面能够观察到的经缓存或 service worker 返回的响应仍按正常归属保存，保留来源标记。

### 8.5 前端错误

- Runtime.exceptionThrown：错误信息、栈、脚本 URL、行列、执行上下文。
- Runtime.consoleAPICalled：按级别、大小和规则保存；默认重点保留 warn/error。
- Log.entryAdded：补充浏览器诊断信息。
- 保留来源并去重；不能把重复 console、exception、log 误算成三个独立故障。
- RemoteObject 的对象内容可能不可用或不再是调用时值；默认保存事件携带的预览/基本值，不执行任意 getter 深挖对象。
- 现有 source map 可用于后续按对应构建版本解析栈，本插件不上传源码作为录制副作用。

## 9. 本地保存、恢复与时间

### 9.1 IndexedDB 职责

IndexedDB 保存已经接受并脱敏的采集数据、谱系、通道状态和导出信息。由扩展后台统一写入扩展自身 origin 的数据库；内容脚本经消息发送数据，不直接在 MES 页面的 IndexedDB 中保存。

扩展 service worker、扩展页面等可共享扩展自身存储；内容脚本直接调用网页存储 API 访问的则是页面存储。Chrome 118+ 的活跃 debugger 会话可维持扩展后台活跃，但仍要应对意外终止。[S14][S15]

建议最小对象仓库：

| object store | 用途 |
| --- | --- |
| recordings | 会话、策略快照、状态、scopeVersion、计数 |
| targets | browserRunId、标签谱系、document/stream 与通道覆盖信息 |
| chunks | 有序事件分片、网络增量记录、压缩元数据 |
| blobs | 正文、截图等有界附件及引用 |
| exports | 问题包生成状态、已导出记录；可选上传信息不得影响本地保存 |

不要求每一类事件建独立 SQL 表；名称可适配既有代码，但语义与索引需保留。

### 9.2 分块与持久化

- 分批写入，按时间或字节数触发，不把全部录制留在内存直到结束。
- 每块包含 recordingId、browserRunId、streamId、chunkSeq、事件范围、校验值。
- 分片写入与对应 checkpoint 在同一事务中提交。
- 原始观测与派生摘要保持引用完整性；不允许已持久化摘要引用停止时丢弃或最终未导出的事件/附件。
- 重试不得产生重复事件；事件/分片 ID 必须稳定。
- 持久化前脱敏；上传前再次验证 schema、大小和引用完整性。
- JSON/NDJSON 文件必须保持有效语法，不用任意字符串截断制造“完整事件”。
- 原生 rrweb 事件很大时采用传输分帧，接收端完整重组后再接受；分帧不等于删掉事件内容。
- 正常关闭标签可能来不及发最后一批，记录 finalFlushConfirmed=false，保留已有分片。

### 9.3 恢复

普通后台重启：

1. 在同一 browserRunId 加载未终结会话和 scope；恢复/对账完成前不默认接受新业务数据。
2. 查询实际仍存活的目标以及 debugger 状态。
3. 对账 page/recorder 实例与 document，防止重复注入。
4. 不确定的区间标 gap；新的 recorder 必须有新基线。
5. 不从当前同域名标签自动补齐未记录的范围。

浏览器重启或扩展重载：

- 更新 browserRunId；旧会话标 interrupted。
- 旧 tabId 不作为新会话授权。
- 已持久化数据仍可封包。
- 用户需要重新选择目标开始新会话；如未来加入“恢复”功能，也要重新核对目标。

### 9.4 时间字段

- 记录 sourceTime、sourceClock、observedAt 和 sourceSeq。
- rrweb 时间、页面 performance 时间、CDP 单调时钟、webNavigation 时间保留各自原值与来源。
- 若归一化到 UTC，保存方法及估计偏差；不确定时 normalizedAt=null。
- 每个源内以序号/本源时钟排序；不同 API 的时钟有偏差，不按近似时间强行推断因果。
- response Date 可能由代理产生且精度有限，只能作辅助线索。
- 停止边界使用本端接受入口及 generation，不信任页面自报时间来绕过截止。
- 后台日志检索使用可配置时间余量；优先使用服务端关联 ID。

## 10. 数据契约

字段统一采用 camelCase。以下示例是虚构测试数据，可调整实现细节，但不可删除影响归属、截止和证据解释的语义。

### 10.1 身份

| 字段 | 规定 |
| --- | --- |
| schemaVersion | 问题包/事件契约版本，例如 1.0.0 |
| recordingId | 本次会话 UUID，导出和 Agent 引用的顶层身份 |
| browserRunId | 浏览器运行期 UUID，普通 service worker 重启不更换 |
| tabInstanceId | 当前被观察物理标签生命周期 UUID |
| browserTabId / windowId | 原生运行时 ID，不作为永久主键 |
| parentTabInstanceId | 可信来源父节点；允许指向已关闭历史节点 |
| rootTabInstanceIds | 授权根引用集合；重叠范围不得重复采集 |
| replacesTabInstanceId | 正式替换关系，不能当作普通父子关系 |
| chromeFrameId / documentId | 扩展侧 frame/document 身份，在事件中按 emitterContext / subjectContext 明确用途 |
| cdpFrameId / loaderId | CDP 侧身份，与扩展 frameId 分开 |
| emitterContext / subjectContext | 已验证消息发送上下文 / 实际观测对象上下文；不确定或跨文档时保留原因与节点映射 |
| streamId / source | 通用来源流 ID 与来源类型；sourceSeq 在该流内严格递增 |
| recorderStreamId | rrweb 实例流 ID；每次重启换新 |
| captureGeneration | 标签全部通道失效时递增，使该标签旧异步任务失效 |
| channel / channelGeneration | 通道名称及其失效代数；单通道失效不影响其他仍存活通道 |
| eventId / sourceSeq | 稳定证据 ID 与源内严格递增序号 |

browserRunId 可以放在 chrome.storage.session 等本次运行状态中，但须验证重启、扩展重载、后台唤醒的实际行为。不能在每次 service worker 进入时无条件生成新运行期 ID。

### 10.2 标签谱系记录示例

```json
{
  "recordingId": "rec-demo-01",
  "browserRunId": "browser-run-01",
  "tabInstanceId": "tab-child-01",
  "browserTabId": 104,
  "windowId": 2,
  "parentTabInstanceId": "tab-root-01",
  "rootTabInstanceIds": ["tab-root-01"],
  "membershipReason": "derived",
  "lineageEvidence": [
    {
      "source": "webNavigation.onCreatedNavigationTarget",
      "sourceBrowserTabId": 101,
      "targetBrowserTabId": 104,
      "sourceFrameId": 0,
      "observedAt": "2026-11-16T02:00:01.000Z"
    }
  ],
  "lifecycle": "OPEN",
  "captureState": "ACTIVE",
  "networkReadyAt": "2026-11-16T02:00:01.080Z",
  "firstBaselineAt": "2026-11-16T02:00:01.120Z",
  "possibleInitialGap": true,
  "captureGeneration": 1
}
```

root/parent 信息是授权与来源记录，不能根据当前 URL 重新推断覆盖。

### 10.3 通用事件示例

```json
{
  "schemaVersion": "1.0.0",
  "eventId": "semantic-a-01:145",
  "recordingId": "rec-demo-01",
  "browserRunId": "browser-run-01",
  "tabInstanceId": "tab-child-01",
  "browserTabId": 104,
  "windowId": 2,
  "emitterContext": {
    "chromeFrameId": 0,
    "documentId": "doc-example-01",
    "verifiedBy": "extension_message_sender"
  },
  "subjectContext": {
    "chromeFrameId": 0,
    "documentId": "doc-example-01",
    "status": "verified"
  },
  "streamId": "semantic-a-01",
  "source": "semantic",
  "recorderStreamId": "rrweb-a-02",
  "sourceSeq": 145,
  "kind": "ui.state_change",
  "sourceTime": 12500,
  "sourceClock": "document_performance_ms",
  "observedAt": "2026-11-16T02:00:12.500Z",
  "captureGeneration": 1,
  "channel": "semantic",
  "channelGeneration": 1,
  "payload": {
    "actionId": "action-19",
    "fieldKey": "weighing.precision",
    "label": "小数位数",
    "elementRef": {
      "recorderStreamId": "rrweb-a-02",
      "nodeId": 42
    },
    "before": {"status": "known", "value": "2"},
    "after": {"status": "known", "value": "3"},
    "evidenceRefs": ["state-a-01:62", "state-a-01:67"]
  },
  "quality": {
    "redacted": false,
    "truncated": false,
    "limitations": []
  }
}
```

原生 rrweb 事件保存在信封的 payload.rrwebEvent 中，保留它自身的类型、节点 ID、时间及结构；不能为了统一 schema 改坏原始事件依赖。

本例 state-a-01 中的两个 ID 表示已经接受并随包导出的 ui.state_snapshot。实际示例包必须同时包含被引用记录，不能仅复制这里的虚构 ID。跨文档 rrweb 事件的 subjectContext 可为空，并附节点上下文映射及原因；不能把 emitterContext 当作默认值。

建议 kind 至少支持：

- lifecycle.session_started / session_stopped / interrupted。
- lifecycle.tab_enrolled / tab_closed / tab_replaced / tab_moved。
- lifecycle.document_started / route_changed。
- ui.action / state_snapshot / state_change / issue_marker。
- browser.exception / console / diagnostic。
- network.request_observed / response_observed / request_finalized。
- capture.channel_ready / channel_lost / gap / late_result_dropped。
- rrweb.event。

### 10.4 网络记录示例

```json
{
  "schemaVersion": "1.0.0",
  "requestKey": "rec-demo-01:tab-child-01:target-104:789.2:0",
  "recordingId": "rec-demo-01",
  "tabInstanceId": "tab-child-01",
  "debuggerSessionKey": "target-104",
  "cdpRequestId": "789.2",
  "redirectOrdinal": 0,
  "request": {
    "method": "POST",
    "url": "https://mes.example.invalid/api/recipe/control/save",
    "bodyRef": "bodies/request-001.json",
    "bodyCaptureStatus": "captured",
    "bodyCaptureReason": null
  },
  "response": {
    "httpStatus": 200,
    "bodyRef": "bodies/response-001.json",
    "bodyCaptureStatus": "captured",
    "bodyCaptureReason": null
  },
  "networkOutcome": "finished",
  "businessOutcome": "failure",
  "businessCode": "VERSION_CONFLICT",
  "serverCorrelation": {
    "requestId": "server-req-example-001",
    "requestIdSource": "response_header:x-request-id",
    "traceId": null,
    "traceIdSource": null
  },
  "actionCandidates": [
    {"actionId": "action-19", "basis": "temporal_proximity", "confirmed": false}
  ],
  "evidenceRefs": ["network-a-01:200", "network-a-01:204"]
}
```

字段缺失使用明确状态。不要将所有 body 结果都表示为 null。

### 10.5 正文与字段状态

请求与响应统一使用 request.bodyCaptureStatus / bodyRef / bodyCaptureReason 以及 response.bodyCaptureStatus / bodyRef / bodyCaptureReason。bodyRef 仅在确有保存并导出可引用的正文附件时存在；不能为未取得的正文创建假引用。bodyCaptureReason 在非正常取得时说明原因，正常 captured/empty 可为 null。

两侧 bodyCaptureStatus 均至少区分：

| 状态 | 含义 |
| --- | --- |
| captured | 已取得并按策略保存 |
| empty | 明确确认没有正文或正文长度为零 |
| not_applicable | 该类数据没有请求体/响应体需求 |
| truncated | 有意保留部分内容；给出原大小（已知时）、保留大小和方式 |
| excluded_by_policy | 类型、域名、脱敏或容量策略排除 |
| unavailable | 浏览器不可取得、缓存淘汰、读取失败等；必须有 reason |
| incomplete_target_closed | 目标关闭时未取得完整证据 |
| incomplete_session_stopped | 用户停止时未取得完整证据 |

redactionStatus 单独表示 none / applied / fully_masked / failed_excluded。被掩码的字段不能伪装为空字符串；脱敏失败默认不持久化原文。

### 10.6 完整性与能力

manifest 中保存 capabilities 和 gaps。例如：

- domTopLevel: available。
- crossOriginFrames: partial。
- sharedWorkerInternals: not_collected。
- networkBodies: bounded。
- initialRequests: possible_gap。
- finalFlushConfirmed: false。
- missingChunks: [已知缺失范围]。
- serverVersion: unknown。
- codeSnapshotMatch: unresolved。

complete 只能指声明范围内的保存与传输完整，不能等同“捕获了浏览器发生的一切”。

## 11. 问题包格式与导出

### 11.1 文件布局

导出文件名使用安全的 recordingId，例如 `mes-evidence-rec-demo-01.zip`。

| 包内路径 | 内容 |
| --- | --- |
| manifest.json | schema、会话范围、策略快照、文件清单、版本、能力、缺口、校验值 |
| summary.md | 供人和 Agent 先读的短摘要 |
| targets.json | 窗口、根/后代、关闭/替换关系、文档/流映射 |
| events/*.ndjson | 语义动作、状态、生命周期、错误和缺口 |
| rrweb/*.ndjson | 带信封的原生 rrweb 事件 |
| network/*.ndjson | 网络事件与最终请求索引 |
| bodies/* | 经过处理的请求/响应附件 |
| screenshots/* | 人工标记等关键截图 |
| README.md | 如何读取包、字段含义、限制、证据引用方式 |

无需为每个小事件生成独立文件。大型数据分片，禁止导出单个无限增长的 JSON 数组。

manifest 的 file 清单包含相对路径、mime、字节数、SHA-256、所属流、事件序号范围。校验值用于检查文件传输/修改，不证明页面数据具备不可伪造性。manifest 本身不做自我递归散列。

文件名来自应用生成的 ID，不直接使用页面标题、URL 路径、错误文本，以避免路径穿越和非法文件名。

### 11.2 summary.md 必须包含

1. 采集记录编号和站点关联环境。
2. 环境、采集起止、浏览器/插件版本、MES 版本及未知项。
3. 根标签与后代概览，以及已经关闭的目标。
4. 关键操作与字段变化，附 eventId。
5. 时间标记、前端异常、异常请求。
6. 可用的 server requestId/traceId 和业务 ID。
7. 缺口、截断、关闭截止及异常中断状态。
8. 建议后续检索的线索；不在插件中冒充已确定根因。

摘要可以由确定性规则生成，LLM 摘要由已有 Agent 后续完成。

### 11.3 本地导出与可选上传

- 生成一个可独立阅读的 ZIP，不要求服务端参与封包。
- 记录所有选中根及后代；采集失败的目标仍在 manifest 中说明，不能无提示从包中消失。
- 可在扩展控制页执行压缩/导出；关闭控制页不停止后台录制，重新打开后可从 IndexedDB 继续整理已保存数据。
- 本地文件导出不会自动出现在服务器；若接入上传，上传状态与采集/导出状态分别管理。
- 上传未确认成功时不自动删除唯一的本地副本；本地清理由明确的保留策略或用户操作触发。

## 12. 环境、日志与代码版本关联

### 12.1 需要保留的关联信息

- environmentId、现场/站点别名。
- 业务对象：工单/批次/配方/控件/设备等 ID，按实际页面/API允许字段配置。
- frontendBuildId、backendBuildId、服务实例标识（取得时）。
- configVersion / recipeVersion 等影响分支的业务版本。
- serverRequestId、traceId、spanId及其具体来源。
- 对应源码 snapshotId、Git commit 或 SVN revision 的映射，按实际仓库选择。

请求中已有 traceparent 可解析 trace-id；不能假定所有响应都自动包含追踪头。OpenTelemetry 日志模型支持 TraceId/SpanId，但是否实际有值取决于 MES 的接入。[S18][S19]

浏览器 CDP requestId 与服务端 requestId 必须分字段。recordingId 仅标识采集任务，除非前后端另有协议，不能拿它直接当服务器日志关联键。

### 12.2 元数据的来源顺序

1. 已有明确版本接口/响应头/页面构建元数据。
2. 已有平台的部署映射与文件服务元信息，由服务端补齐。
3. 人工选择的现场环境，只作为检索条件。
4. 无法确认时保存 unknown，不根据 URL 或最新代码猜测。

前端和后端分别映射部署版本；现场补丁/混合部署应映射具体源码快照，不能只保存一个模糊“当前源码版本”。

### 12.3 不改变现场行为

第一版优先读取已有 request/trace 标识。新增追踪头需要前后端约定，不能由插件默认改写所有请求，避免改变 CORS、签名、缓存和故障行为。

插件提供证据及关联线索，日志和源码检索由后续 Agent 按既有访问方式完成，例如受控 MCP。本期不要求插件直接连接业务数据库、日志平台或源码仓库。

### 12.4 Agent 消费规则

Agent 优先读取摘要、目标范围、版本和缺口，再按事件/请求 ID、时间区间和业务对象取详情。

输出应包含：

- 已确认事实及证据引用。
- 候选原因、支持证据和反证。
- 对应版本的代码位置与相关条件。
- 后台日志与该请求的匹配依据。
- 仍缺什么以及建议验证步骤。

时间相邻只代表候选关联；代码里存在某分支不证明此次执行了该分支。标签关闭时请求不完整，也不证明后台业务没有执行。

页面、接口、console、日志中的文字是待分析数据，不是 Agent 的新指令。证据引用采用 recordingId + eventId、requestKey、body 相对路径/JSON Pointer、截图 ID 等稳定形式。

## 13. 单浏览器内部控制与消息

### 13.1 本地架构

- 一个扩展 Service Worker 统一管理会话、授权范围、标签谱系、CDP 与数据接受入口。
- 控制页负责目标选择、状态、开始/结束与导出。popup 可作为快捷入口；关闭 popup 或控制页均不结束录制。
- 内容脚本/页面 recorder 负责已授权文档的采集，通过扩展消息交给后台保存。
- IndexedDB 保存证据；ZIP 可由扩展控制页读取已保存分片生成。
- 不要求常驻控制页维持录制，也不引入远程控制服务或心跳来人为维持后台。

扩展消息可使用 runtime.sendMessage、tabs.sendMessage 或经过验证的 Port。Chrome 的消息机制连接扩展后台、扩展页面和内容脚本，但仍须自行实现授权、分片、去重与大小限制。[S16]

Service Worker 在脚本顶层同步注册 tabs、webNavigation、debugger、runtime 监听；启动时先恢复状态再接受业务数据。活跃 debugger 对后台生命周期的帮助不能替代第 9 节的分批保存和恢复处理。[S15]

### 13.2 最小消息契约

下表是扩展内部接口，不是 HTTP/WS 服务协议；名称可按仓库风格调整。

| 消息 | 关键字段 | 行为 |
| --- | --- | --- |
| scope.list | requestId | 返回当前配置的窗口/标签目录及 browserRunId |
| session.start | commandId、recordingId、browserRunId、rootBrowserTabIds、policy | 校验并建立根集合，返回本地启动状态 |
| session.add_root | commandId、recordingId、明确目标、scopeVersion | 添加当前配置中的一个根，记录授权起点 |
| session.mark | commandId、recordingId、目标、备注 | 插入时间标记；目标必须已纳入 |
| session.stop | commandId、recordingId、reason | 先关闭全部接受入口，再清理和持久化终结状态 |
| session.status | recordingId | 返回目标、通道、保存进度、缺口与会话状态 |
| page.handshake | recordingId、文档身份、recorder实例信息 | 后台根据真实发送方核验授权，并返回有效采集票据 |
| capture.batch | recordingId、streamId、chunkSeq、代数、分帧信息 | 校验来源，完整重组后通过接受入口并保存 |
| export.create | recordingId | 对已停止或已中断会话的保存数据生成问题包 |

START/STOP/新增根等控制命令仅接受已验证的扩展控制页面；页面桥不能发出这些命令。schema、大小与真实发送上下文均必须核验，不能仅信任 payload 的 tabId。

兼容最低 Chrome 版本时，异步 onMessage 响应采用该版本已验证的方式；例如返回字面值 true 并调用 sendResponse，不直接假定所有目标版本都支持监听器返回 Promise。[S16]

### 13.3 幂等、停止与恢复

- 同时只允许一个活动 recording；重复 START 返回现有状态，不重复 attach 或注入。
- commandId 用于本地重复点击/消息重试去重；不需要分布式命令路由。
- STOP 先同步关闭所有目标的接受入口。终结标记应尽快持久化，只有完成对应状态提交后才响应已成功停止；不能等待请求自然结束才关闭入口。
- 已停止 recording 不可被迟到 START、旧文档消息或旧 browserRunId 恢复。重新录制必须创建新 recordingId。
- 清理、保存和 ZIP 生成分别报告进度；清理失败不打开原先已关闭的入口。
- 迟到的 debugger attach 若成功，立即释放本次连接，不启用新采集域或将目标改回 ACTIVE。
- 普通后台恢复先按第 9 节对账；无法确认运行状态时标 interrupted/partial，不盲目恢复。

关闭控制页或导出失败后，可重新打开控制页查看状态、结束录制或重新生成 ZIP。无法保存时明确提示错误，不能显示虚假的“已导出”。

## 14. 数据保护、域名与资源预算

### 14.1 采集策略

每次开始冻结 policyVersion 和策略快照：

- 允许页面 origin、允许 API origin/path、受支持请求类型。
- 输入/页面文本/属性的保留与掩码规则。
- 请求头、查询参数、请求/响应正文、console 的脱敏规则。
- 截图规则和数据大小上限。
- 每标签/本次会话预算与采集能力。

密码、Authorization、Cookie、Set-Cookie、会话令牌等不得持久化或上传。CDP 返回后立即在扩展侧处理；rrweb/页面侧尽可能在跨上下文转发前处理。

业务字段按允许规则保留，特别是排障必需的精度、状态、版本及业务 ID。若业务 ID 需要替换，必须保证后端授权检索仍有映射；不能不可逆掩码后又要求直接查日志。

rrweb 的输入掩码不自动覆盖 URL 属性、网络正文、console 和截图。按各通道分别验收。原始快照脱敏须保留有效结构与节点关系；无法安全保留的区域应整体屏蔽并记录范围，不随意删 mutation。

截图中的像素需单独遮挡或停用，不能把 DOM 文本已掩码当作截图已脱敏。

### 14.2 默认预算（工程初值，必须可配置）

以下是建议的首轮实现默认值，不是性能承诺，也不是浏览器固定配额：

| 项目 | 初始建议 | 超限行为 |
| --- | --- | --- |
| 本次会话同时标签数 | 10 个软提示阈值 | 明确提示并允许按配置提高；硬上限触发时列出未采目标 |
| 单次录制时长 | 30 分钟提醒 | 提示继续/结束，不默默丢弃 |
| IPC 单传输片 | 128 KiB（UTF-8 字节） | 完整分帧/重组，不能截断事件 |
| 本地落盘触发 | 1 秒或约 256 KiB | 批量事务，结合实际负载调整 |
| 单个完整 DOM 基线 | 8 MiB 序列化数据预算 | 无法容纳则标 DOM unavailable/partial，其他通道继续 |
| 单请求/响应正文保存 | 各 1 MiB | 配置性截断或排除；保留状态/大小/原因 |
| 本次录制 | 100 MiB 软提示、200 MiB 默认硬预算 | 到硬预算终止新增采集并保留诊断空间 |
| 正文读取并发 | 每标签 2 个起步 | 有界队列，停止时失效 |
| 事件重组/队列 | 有界，初值 16 MiB | 写 gap、停止受影响流或建立新基线，不伪装完整 |
| 停止后排空已接受队列 | 目标 5 秒，超时明确诊断 | 不等待新的网络返回，不重新采集 |

正文大小上限是保存/上传约束。getResponseBody 可能一次返回完整字符串，不能把上限误写成浏览器保证只读取前 N 字节。结合已知 Content-Length/MIME、CDP 有界缓冲与读取并发控制峰值；未知/大二进制内容保守排除。

JSON 正文若因截断无法可靠脱敏，排除正文并保存原因；不输出看似有效的残缺 JSON。大快照超限后不能直接截断其 JSON，当作成功基线使用。

### 14.3 性能测量

记录开启/关闭采集的对照结果：操作响应、页面卡顿、事件吞吐、CPU/内存、落盘队列、注入/attach 延迟、丢失计数。使用同一测试流程测量，不宣称固定“零影响”或未经测试的吞吐量。

数据量优先通过关闭无诊断价值的鼠标移动高频采样、限制视觉资源、控制正文类型等降低。必须保留业务状态和完整事件依赖。

## 15. 模块边界与推荐实现组织

技术选择以现有仓库为准；新建时推荐 TypeScript + Manifest V3、rrweb record、IndexedDB。UI 可用已有 React/Vite 技术；无需引入新的前端框架。

| 模块/建议目录 | 责任 |
| --- | --- |
| extension/ui | 目标选择、采集状态、时间标记、摘要预览、导出 |
| extension/background/session | 会话、scope、停止 gate、恢复 |
| extension/background/lineage | 标签来源、递归纳入、替换/移动/关闭 |
| extension/background/cdp | 目标/子 session、Network、Runtime、Log、读取队列 |
| extension/content/bootstrap | 作用域握手、document生命周期、隔离侧消息 |
| extension/page/recorder | rrweb、输入/页面状态与语义采集 |
| extension/storage | IndexedDB、分块、去重、版本升级 |
| extension/export | 问题包、摘要、校验与下载 |
| shared/contracts | 事件、网络、目标、协议及运行时校验 |
| upload-adapter（可选） | 如需要，适配已有文件服务；不作为本地交付依赖 |
| fixtures | 模拟 MES 页面、接口、弹框、派生标签和错误场景 |
| tests | 生命周期、范围、截止、导出及真实浏览器集成测试 |

约束：

- UI 不直接控制 CDP 生命周期，统一经 session manager。
- 所有业务采集通道经过同一个 scope/generation 接受入口。
- 录制、保存、导出与可选上传解耦；上传失败不扩大或改变采集范围。
- 不为此引入独立图数据库、MQ或通用规则平台。
- 选择器、历史谱系和当前采集通道状态分离，不把标题或 URL 当主键。
- 录制脚本随包发布，生产构建不依赖远程执行代码。
- 依赖版本和兼容结果写入 README 与 manifest 元数据。

## 16. 实施里程碑

按以下顺序执行，可分 PR，但最后不能只交一个静态演示界面。

### A0：能力验证

在固定测试页验证：

- 多根标签 attach、派生来源事件、快速打开后关闭父页。
- MAIN world 下的输入/程序赋值、rrweb 基线。
- 同源/跨源 iframe 的流模型和无重复要求。
- 目标关闭与迟到正文结果的截止 gate。
- 首请求捕获率与 gap 标记。
- 实际 Chrome 版本及企业权限限制。

输出简短技术验证记录，锁定库版本和无法支持的边界。无需访问生产 MES 才能完成这些测试。

### A1：范围与生命周期

交付当前 profile 的多窗口选择、多个根、递归派生、移动/替换/关闭、明确状态与严格停止。

### A2：证据采集与本地闭环

交付 rrweb、业务语义、网络/错误、脱敏、IndexedDB、摘要、ZIP导出；使用模拟 MES 场景完成端到端验证。

### A3：问题包与 Agent 验证

完成分片与引用校验、真实浏览器验收、异常恢复和 Agent 消费说明。给出模拟 MES 故障对应的源码/后台日志示例，验证问题包可用于定位线索。可选文件服务对接另列，不阻塞本地交付。

### 完整交付判断

A0–A3 构成本期单浏览器完整交付。无需协调后端、浏览器配对或跨配置联采，也不能只交静态界面而缺少真实采集与问题包。

主验收流程：在同一 Chrome 配置的两个窗口选择 A、B；A 新建 C，C 新建 D；把 C 拖到另一窗口；关闭 A；B 发起未完成请求后关闭；C/D 继续操作；最后手动结束。问题包须准确保留派生关系、移窗记录、A/B 的截止、未完成请求及 C/D 的持续采集。

## 17. 验收矩阵

优先为范围、生命周期、异步截止和数据契约编写必要测试；使用真实浏览器验证平台行为。单元测试通过不能替代真实扩展运行。

| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| T01 | 两个窗口，只选 A、B，C 未选 | A/B有证据；C无rrweb、DOM、正文、console业务记录 |
| T02 | 勾选整个窗口后 Ctrl+T 新建 D | D不因同窗口而自动采集 |
| T03 | A派生B，B派生C | B/C递归加入，谱系正确，只启动一次 |
| T04 | 子页在新窗口打开 | 子页加入，新窗口其他页不加入 |
| T05 | A关闭，B/C仍开 | 仅A停止，B/C继续 |
| T06 | B关闭，A/C仍开 | 仅B停止，C保留父节点历史 |
| T07 | 关闭一个含多个目标的窗口 | 该窗口实际关闭目标均停止；其他窗口目标继续 |
| T08 | 把B拖到另一个窗口 | 继续采集，不重复录制，不把tabs.onDetached当关闭 |
| T09 | 未选C打开与A相同URL | C及其无关后代不自动加入 |
| T10 | 开始前旧子页，或添加A前A已创建B | 不追溯纳入旧子页/B；添加A后新建C则按谱系纳入 |
| T11 | 父关闭与子创建通知乱序 | 有足够可信证据时正确纳入；不足时明确未纳入，不猜测 |
| T12 | 重复onCreated/导航来源通知 | 幂等，无双attach或双recorder |
| T13 | target=_blank/noopener/noreferrer | 输出每种方式实测结果；可靠来源时加入，无来源时提示 |
| T14 | Ctrl/Cmd点击、中键、右键新页/新窗 | 同T13，记录目标版本兼容矩阵 |
| T15 | window.open 新建与命名窗口复用 | 新建按谱系；已有未选窗口不误纳入 |
| T16 | 新页脚本立即发送唯一标记API | 记录捕获结果及actual ready/gap，不冒充首请求必达 |
| T17 | 请求未结束时关闭目标 | 不再读取正文，已有数据保留，标incomplete_target_closed |
| T18 | 关闭后body Promise或截图返回 | payload被丢弃，不复活目标；只允许诊断计数 |
| T19 | 截止前已排队数据尚未落盘 | 可完成写入，保留原事件归属 |
| T20 | 全局停止时页面仍轮询/推送 | 截止后无新增业务证据，连接清理，未完成项明确 |
| T21 | 全部目标已关闭再新建无关页 | 活动数为0，新页不被自动选中 |
| T22 | 页面刷新、完整跨页导航 | 新document/基线，旧事件不串入新页面 |
| T23 | Vue SPA路由/hash变化 | 正确记录路由，不伪造新文档身份 |
| T24 | BFCache前进后退 | 正确恢复或新建流，基线和缺口明确 |
| T25 | 正式tab replacement | 继承范围并记录替换；旧onRemoved不误停新实例 |
| T26 | 同源、跨源、动态iframe | 基线/映射可追溯，无重复；转发者与实际观测文档不混淆；无权限明确缺口 |
| T27 | 输入value/checked被程序修改 | rrweb或补充状态记录可见；不能只测试人工输入 |
| T28 | 短暂toast、弹框、按钮禁用 | 关键变化保留，不只保存最终画面 |
| T29 | 两tab、两recorder都出现nodeId=42 | 元素引用仍正确隔离 |
| T30 | 重定向、多并发请求、ExtraInfo早到/迟到 | 请求键不覆盖，重定向各跳头信息与正文不串位；无法匹配明确标记 |
| T31 | HTTP200业务失败、HTTP500、网络失败 | 三层结果正确，不按单一状态归因 |
| T32 | 请求体/响应体为空、超限、读取失败、停止未完成 | 双侧字段路径一致，各状态明确区分，bodyRef可实际解析 |
| T33 | WebSocket/SSE业务消息 | 如启用，归属正确且关闭即停；不只记录握手冒充完整 |
| T34 | shared worker同时服务选中/未选页 | 不混入无法归属的其他页业务内容 |
| T35 | 后台目标截图执行期间快速切到未选页 | 仅绑定指定target截图，不误截、不误归属、不主动切换标签 |
| T36 | F12/用户取消调试 | 网络降级可见，不无限重连；仍有效的页面/语义通道继续保存，不被错误代数全部拒绝 |
| T37 | 跳转未授权域名再返回 | 停采/缺口明确；返回后重新建立有效基线 |
| T38 | 密码/token出现在DOM、URL、接口、console | 导出所有通道均按规则脱敏 |
| T39 | IPC大事件、分片重试、队列超限及重组时停止 | 无非法JSON/重复；缺口可解释，新流有基线；摘要不存在悬空evidenceRefs |
| T40 | 后台重启/浏览器重启 | 同browserRunId正确对账；新运行期不冒用旧tabId授权 |
| T41 | 插件离线，或可选上传断网 | 已保存数据可本地导出；录制不依赖外部服务 |
| T42 | 网络通道断开后重建，同URL并发请求 | 新调试会话/请求键不覆盖旧记录，各标签归属正确 |
| T43 | 多根启动时一根无权限或已关闭 | 其他有效根继续，失败根与每通道ready/缺口明确 |
| T44 | 手动结束时多标签/iframe/专属worker仍活动 | 所有已纳入目标入口关闭，迟到payload丢弃，页面后续轮询不新增证据 |
| T45 | 重复START/STOP、STOP后迟到START、旧运行期消息 | 不重复挂监听，不复活已终结会话，旧消息不取得新授权 |
| T46 | 系统时间调整、浏览器API与服务端时钟有偏差 | 保留原时钟/偏差，源内顺序正确，日志检索有余量 |
| T47 | 字段与日志/源码版本未知 | 标unknown/unresolved，不填“最新版本”假装已匹配 |
| T48 | 导出后重新读取并校验 | manifest路径、hash、事件范围、正文引用与缺口一致 |
| T49 | 实施提供完整模拟问题给分析Agent | Agent能引用步骤、请求、状态、关联线索及缺失，而无需解析整包到上下文 |
| T50 | 关闭popup/控制页后继续操作，再打开控制页 | 采集独立继续，状态可恢复，能够手动停止及导出 |

T13/T14 的关键常用打开方式若在目标版本中存在不可接受的漏纳入，必须在交付前解决或明确列为限制，不能用“可能有缺口”掩盖基本派生功能失效。

T16 是采集完整性测量，不要求在普通扩展模型下伪造零丢失。报告必须列出总创建次数、首请求成功捕获数、起始缺口和版本。

## 18. 交付清单与完成标准

开发 Agent 应交付：

1. 可构建、可加载的扩展源码与构建产物。
2. 安装、配置、权限说明和用户操作说明。
3. 可运行的模拟 MES 页面/API，覆盖多标签派生与典型错误。
4. 事件/问题包 schema、示例包、包校验器或等效校验命令。
5. 扩展内部消息说明与本地数据生命周期说明；上传仅在明确实现时提供适配说明。
6. 针对关键不变量的测试和真实浏览器验收记录。
7. 依赖锁定信息、已验证浏览器版本、已知限制。
8. 未接入的真实环境配置/接口清单，明确区分 mock 与真实实现。
9. 针对现有 Agent 的消费说明：先摘要、按需详情、源码/日志匹配与证据引用。
10. 简短实现说明：做了什么、如何验证、还有哪些具体缺口。

完成标准：

- 用户能明确选择目标，不误采范围外业务数据。
- 根、子、孙标签的纳入与关闭规则一致。
- 关闭后异步结果不会泄漏到问题包。
- 页面/请求/错误/版本信息有稳定可追溯的身份。
- 缺失、截断、失败和未知信息有明确表示。
- 单浏览器本地流程可独立工作，多窗口/多根/后代场景有真实验证。
- 不以静态UI、mock成功状态或单元测试代替实际浏览器采集。

## 19. 决策记录与可配置项

| 项目 | 本文决定 |
| --- | --- |
| rrweb | 采用录制端；不实现播放器 |
| 浏览器范围 | 一个 Chrome profile，可有多个窗口；本期不跨配置/浏览器 |
| 根集合 | 开始时精确冻结，窗口勾选或全选展开为当前标签 |
| 派生关系 | 浏览器来源事件；递归；无来源不猜测 |
| 父关闭 | 只停父；子孙独立继续 |
| 窗口迁移 | 继续 |
| 已有命名目标复用 | 不自动扩大范围 |
| 关闭尾包 | 只排空截止前已接受的数据；截止后才返回的正文/截图不追加 |
| 会话停止 | 同步关闭本次所有目标的接受入口，再清理和整理数据 |
| 页面改写 | 不自动刷新、重发、改请求或暂停页面 |
| 代码/日志 | 后续 Agent 按既有方式检索，版本必须匹配 |
| 完整交付 | 当前Chrome配置的多窗口/多标签录制和本地问题包 |
| 身份 | recording、browserRunId、tab实例、document、stream分层隔离 |
| 默认域名/接口 | 配置化，不猜真实环境 |
| 新增基础设施 | 核心功能仅依赖扩展与本地存储；文件服务上传可选 |

实施前由配置补齐，通常不影响本地原型开发：

- 现场域名/API域名与访问权限策略。
- MES接口成功/失败码协议。
- 需要保留的业务字段和业务ID。
- 版本信息来源及部署包到源码快照的映射。
- 如需上传：文件服务上传/下载接口与鉴权适配。
- 企业允许的Chrome最低/实际版本。
- 数据保留周期和容量预算。

## 20. 官方参考资料

资料核实日期：2026-11-16。下列链接用于验证平台能力与限制；状态机、协议、默认预算和验收方案是本项目设计。实现时按锁定版本再次验证，不直接依赖未稳定的实验性协议特性。

- [S1 — Chrome Tabs API](https://developer.chrome.com/docs/extensions/reference/api/tabs)：标签身份、opener、创建/关闭/移动/替换、权限。
- [S2 — Chrome Windows API](https://developer.chrome.com/docs/extensions/reference/api/windows)：窗口分组与标签目录。
- [S3 — Chromium tabs profile 过滤实现](https://chromium.googlesource.com/chromium/src/+/ada4c40d17fb6849e52ed47ba0cee6c95a55845a/chrome/browser/extensions/api/tabs/tabs_api.cc)：固定源码快照，佐证按配置隔离的能力边界。
- [S4 — Chrome WebNavigation API](https://developer.chrome.com/docs/extensions/reference/api/webNavigation)：新导航目标来源、文档/导航、事件顺序与时钟。
- [S5 — Chrome Debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger)：目标、子session、调试中断与域。
- [S6 — Chrome Scripting API](https://developer.chrome.com/docs/extensions/reference/api/scripting)：注入目标、执行世界与权限。
- [S7 — rrweb Guide](https://rrweb.com/docs/guide)：独立录制、事件输出、停止与配置。
- [S8 — rrweb Events](https://rrweb.com/docs/events)：基线、增量依赖、顺序与导航。
- [S9 — rrweb Cross-origin iframes](https://rrweb.com/docs/recipes/cross-origin-iframes)：父/子页面协作录制。
- [S10 — Chrome Content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)：DOM读取、隔离世界、frame与通信。
- [S11 — MDN MutationObserver.observe](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver/observe)：观察节点、属性、文本与旧值。
- [S12 — MDN input event](https://developer.mozilla.org/en-US/docs/Web/API/Element/input_event)：程序赋值与input事件边界。
- [S13 — CDP Network](https://chromedevtools.github.io/devtools-protocol/tot/Network/)：网络事件与正文读取；开发时使用与浏览器兼容的协议类型。
- [S14 — Chrome Storage and cookies](https://developer.chrome.com/docs/extensions/develop/concepts/storage-and-cookies)：扩展存储归属、持久化、配额。
- [S15 — Extension service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)：后台生命周期与debugger会话。
- [S16 — Chrome Message passing](https://developer.chrome.com/docs/extensions/develop/concepts/messaging)：扩展内部消息、异步响应与发送方验证。
- [S17 — WHATWG noopener/noreferrer](https://html.spec.whatwg.org/multipage/links.html#link-type-noopener)：链接来源关系的边界。
- [S18 — W3C Trace Context](https://www.w3.org/TR/trace-context/)：traceparent与trace-id。
- [S19 — OpenTelemetry Logs](https://opentelemetry.io/docs/concepts/signals/logs/)：日志中的TraceId/SpanId等关联字段。
- [S20 — rrweb Incremental snapshots](https://rrweb.com/docs/observer)：DOM批量变化、输入及节点观察的实现背景。
- [S21 — CDP Page](https://chromedevtools.github.io/devtools-protocol/tot/Page/)：绑定调试目标的截图命令；实现时验证目标版本与后台标签行为。

---

**给开发 Agent 的最终执行要求：按里程碑完成可运行实现，优先保证范围、谱系、关闭截止与证据归属。遇到平台限制时记录具体限制和验证结果，选择不会误采范围外标签的实现；不得静默缩小用户需求，也不得用伪完整数据掩盖缺口。**


