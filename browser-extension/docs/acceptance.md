# 实现与验收记录

日期：2026-11-17（Asia/Shanghai）。本记录区分本地模拟 MES 与公开 web.dev 实测，生产 MES 尚未接入。

## 当前交付

- `complete-evidence-collector-acceptance` **41/44**，第 9 组网络缺口与密码策略修复完成；7.2、7.3、7.5 的原生操作仍待验收，不归档。
- `npm run check`：TypeScript、**61 项单元/契约测试**与生产构建通过；随后测试辅助代码调整后 TypeScript 再次通过。日志在 `output/playwright/network-investigation-20261117/password-only-check.log`、`typecheck-final.log`。
- 最终构建 Chrome for Testing **157.0.8103.78** / macOS arm64：主流程 **50**、网络专项 **11**、权限 **12**、第 7 组 **24**、P0 **20**、公开 web.dev **6**，共 **123 项浏览器断言通过**，涉及 **43 个 T 编号**；不是完整 T 项通过数量。
- **23 个新 ZIP 全部通过**结构、散列、身份、基线及引用闭包校验，汇总 `output/playwright/phase11-validation.json`。统一构建 hash：`597f0cd987465b79c91c964d926efc4bc6fbb668a6f765581ab16b31222c480f`。
- 用户明确确认默认仅保护登录密码：`policyVersion=3.0.0`。普通文本、输入、URL 参数、请求头、Cookie/Bearer/JWT、令牌与业务字段保留原值；密码输入、密码 autocomplete、明确密码字段及 HTTP Basic 密码保护。截图、授权范围、预算和 STOP 约束继续生效。
- 原录制 `本地测试/mes-evidence-2d1e0076-0abb-4a31-b061-49bbf742ea15` 未修改；它的缺失正文无法从旧包补回。新行为来自重新采集，不把新包当作旧现场恢复。

## 第 9 组：真实录制问题与用户策略调整（2026-11-17）

| 问题 / 决定 | 修复与验证 | 证据及边界 |
| --- | --- | --- |
| POST 请求正文缺失 | 同一路径实测为 text/plain、73 字节 JSON 数组；修复后原值保存，密码字段单独保护。支持自由文本、JSON 与重复表单参数 | `phase11-webdev/default.json`、`configured.json`：两次请求正文均 captured，originalBytes/savedBytes 均为 73 |
| POST 响应正文缺失 | 公开页面响应解码后 1,418,112 字节；旧 2 MiB Inspector 资源缓冲报告淘汰。现在累计解码字节，默认 1 MiB 明确超限；缓冲随配置调整，编码/协议/缓存失败分别说明 | `network-investigation-20261117/probe.json` 为旧设置复现；默认新包为 `decoded_body_size_limit`，不是读取失败 |
| XSSI 包装 | 真实响应前缀为 `)]}'` + LF；只识别该精确 LF/CRLF 包装，后续须完整 JSON 解析，不执行脚本 | 配置 2 MiB 的 `phase11-webdev/configured.zip` 响应 captured，原始 1,418,112 字节、保存 1,418,107 字节（去掉 5 字节前缀） |
| frame 首次请求 | CDP documentURL + frameId 判定请求来源授权，不再依赖 frameNavigated 先到；缺失元数据仅允许同 loader 缓存，Chrome document 绑定不能借用旧文档 | `phase11-network/default-budget.zip` 同源新 frame 的 Document 和首次 Fetch 均存在；同进程及 OOPIF 未授权请求实际发生但不入包。旧包泛化 gap 未包含 frame/请求上下文，无法证明旧场景具体是哪条请求 |
| ExtraInfo 状态 / 串位 | 明确 false 标 not_expected；未知标志保留屏障；策略排除跳仍占空 hop；排队读取前后都验证当前 hop | Service Worker 直返及 SW→网络重定向实测，最终双侧头正确；排除 hop、未知屏障、早晚 ExtraInfo 与重定向复用另有单测 |
| 长文本阻塞 | 旧通用 token 正则对 10 万连续字符超过 5 秒；首次 2 MiB 实测暴露后台阻塞。用户关闭通用脱敏后该正则移除，2 MiB 长字符/连字符子进程测试有 5 秒超时保护 | `tests/network-regression.test.ts`；修复后配置 2 MiB 的 gzip 响应完整保存，无卡住。卡住的独立测试进程已按 PID 和专属 profile 清理 |
| 仅密码保护 | 普通输入、DOM 属性、URL token、Authorization Bearer、Cookie、console 和接口令牌保留；初始密码、后续输入、显示密码切换、JSON/表单/URL/Basic 密码保护 | 主流程和网络专项双向检查原值存在/密码不存在；P0 另行显式配置额外敏感区域，属于可选规则能力，非默认策略 |

最终执行入口及产物：

- `npm run test:network` → `output/playwright/phase11-network/`：11 项、2 包；端口 4517/4518，独立 profile。
- `npm run test:browser` → `output/playwright/phase11-main/`：50 项、4 包。
- `npm run test:permissions` → `output/playwright/phase11-permissions/`：12 项、5 包；原生产 manifest，准备阶段预授权，不计原生弹窗验收。
- `npm run test:phase7` → `output/playwright/phase11-phase7/`：24 项、9 包。
- `npm run test:p0` → `output/playwright/phase11-p0-verified/`：20 项、1 包。
- `npx tsx output/playwright/network-investigation-20261117/webdev-password-only.ts` → `output/playwright/phase11-webdev/`：6 项、2 包；独立 profile 只授权 web.dev，通过测试主动重载公开 Discover 页面触发自然请求，不单独重发 POST。不是用户原会话，也不代表生产 MES 验收。

失败与中间构建保留：phase10 系列记录最初 OOPIF 诊断预期、2 MiB 长文本阻塞及 XSSI 前缀未解析；phase11-p0 首次旧断言仍要求隐藏 URL token，按用户新策略调整后复测通过。它们不计入最终 123 项通过。所有最终报告绑定同一构建；旧 7.2/7.3/7.5 缺口及 Chrome 125 兼容边界保持原结论。

协议依据：[CDP Network 定义](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json) 中 documentURL、hasExtraInfo/redirectHasExtraInfo、dataLength 与正文缓冲；本轮以 Chrome 157 实测约束其适用范围。

## 前轮交付记录（2026-11-16，历史策略）

- 变更 `complete-evidence-collector-acceptance` 当前 **36/39**。本次推进 7.5 的撤权隔离与恢复，修复实际竞态并补齐可自动验证的权限场景；7.2、7.3、7.5 仍缺原生界面操作，不归档。
- `npm run check`：TypeScript、**50 项单元/契约测试**和生产构建通过，日志 `output/playwright/phase9-check.log`。本次新增 6 项权限边界检查；初次失败反例另行保留。
- Chrome for Testing **157.0.8103.78** / macOS arm64：最终构建的主流程 **49**、P0 **20**、权限专项 **12**，合计 **81 项浏览器断言通过**，涉及 **35 个 T 编号**。这不是完整 T 项通过数量；P1、容量和其他平台专项本次未重跑，保留各自历史构建与结论。
- 本次最终构建新采 **10 个 ZIP**，全部通过结构、hash、身份、基线和引用闭包校验，汇总 `output/playwright/phase9-validation.json`。构建 hash：`fc7f3d4b15ad42150693749cfc9b256ccd843bd6196dd763376db5492bb54d44`。前轮 `phase8-validation.json` 的 135 项断言和 23 个包属于前轮证据集，不计作本次构建实测。
- API/语法技术下限仍为 125；前轮准确选择扩展 worker 后，Chrome 125 页面/语义就绪，但网络/错误收到 `canceled_by_user` 并降级，未通过兼容验收。本次未重测 125，不宣称 125+ 全版本支持。详见 [接入清单](mes-onboarding.md)。
- 真实 MES 尚未接入，可选上传未启用。全部测试使用独立 profile，结束仅关闭本任务浏览器和辅助服务。

## 第 7.5 组撤权修复与实测（2026-11-16）

权限专项执行期间使用与生产 dist **字节一致的 manifest**。准备阶段先用 fixture host 在独立 profile 预授权，关闭浏览器、还原 manifest 后才执行场景；manifest SHA-256、权限前后值与准备步骤见 `phase9-permissions-final/permission-setup.ndjson` 和 `permission-actions.ndjson`。撤回通过真实 `chrome.permissions.remove` 和浏览器事件完成，混合/全失败使用控制页 RPC 启动；**不是原生权限弹窗、原生撤权界面或会话内重新授权验收**。场景间的测试权限重置不算权限恢复操作。

| 修复/场景 | 结果与证据 | 边界 |
| --- | --- | --- |
| 撤权异步窗口 | 同步删除受影响授权、使所有旧通道代数失效，再查询权限和清理；未撤权根保留原 generation 与流 | `phase9-permission-red.log` 复现旧 token 在等待查询时仍有效；修复后单测通过 |
| 子 frame 旧正文 | 撤回子域时同时重建父统一流和该标签 CDP 会话，迟到正文丢弃；父页新基线后继续，其他根不受影响 | `child-revoked.zip`。先读取真实子请求正文，再暂挂返回值，撤权后释放；不是声称自然网络延迟 |
| 未取得页面票据的 frame | 撤权范围也检查实际 CDP frame URL，不能只靠已登记文档 | `phase9-early-frame-red.log` 为失败反例；修复后的单测证明旧 token 失效。该竞态用确定性模拟覆盖，不冒充原生时序 |
| 权限快照 | 查询完整快照后原子替换，仅最新查询和原 recording 可提交；迟到查询不能复活授权 | 新增原子更新/晚到查询、域名/通配符/端口边界及重核期间 STOP 检查，合计 6 项新增单测 |
| 未授权导航与返回 | 真实未授权 origin 上执行字段/请求哨兵无业务证据；返回仍授权 origin 后保留成员并新建文档、流和基线 | `navigation-returned.zip`；区别于撤回后在同一会话重新授权，后者仍待原生操作 |
| 根撤权与后台恢复 | 被撤权根 BLOCKED，唯一业务哨兵不入包；真实终止并唤醒 worker 后继续拒绝该根，其他已授权根恢复 | `root-revoked.zip` |
| 混合根与全部失败 | 真实权限状态下只保存有效根业务；全部未授权时保存 FAILED 诊断、无业务事件/请求且 UI 显示失败 | `mixed-roots.zip`、`all-failed.zip`；未完成“点击开始后实际原生拒绝弹窗”的链路 |

最终构建的运行入口与证据：

- `npm run test:permissions` → `output/playwright/phase9-permissions-final/`：12 项、5 个包。
- `npm run test:browser` → `output/playwright/phase9-regression-final/`：49 项、4 个包。
- `npm run test:p0` → `output/playwright/phase9-p0-final/`：20 项、1 个包。
- `npm run check` → `output/playwright/phase9-check.log`；OpenSpec 严格检查 → `phase9-openspec-validation.log`。

失败历史保留：`phase9-permissions/` 已通过子 frame 撤权部分，随后重新请求 localhost 时等待原生弹窗而超时；没有伪造允许结果。`phase9-permissions-v2/`、`phase9-regression/`、`phase9-p0/` 为中间构建，不计最终构建 81 项。普通浏览器回归仍使用复制构建的 fixture 预授权，权限模式分别写入报告。

原生辅助脚本已补上窗口复选框冻结后再按快捷键、全拒绝 FAILED、未授权导航返回、原生取消后后台唤醒检查；移除与本轮剩余任务无关的重复 BFCache/reload 步骤。`phase9-native-readiness/` 到达 `native-unrelated` 等待点后按设置的 1.5 秒超时退出，没有执行原生动作。原生工具本次连接仍在 20 秒后超时；7.2 的快捷键、7.3 的右键及首请求、7.5 的原生许可/撤回/重新授权/子 frame 组合与 F12/取消仍待验收，见 [操作清单](native-acceptance.md)。

## 第 7–8 组实施与证据（前轮历史）

| 范围 | 本轮结果 | 证据 / 边界 |
| --- | --- | --- |
| 范围与来源 | 同 URL 未选页及其后代、新窗口内无关页排除；中间节点/整窗关闭；移窗后原流业务连续；真实父页同步打开后立即关闭，子页继续 | `phase7-release/scope.zip`、`phase7-platform-verified/platform-2.zip`。本次固定选择与命名组合补充见下文；窗口全选后原生快捷键新页和右键菜单仍归 7.2/7.3 |
| 首请求与重复通知 | 逐后代记录 created/lineage/networkReady/baseline、服务端首请求到达和实际捕获；模拟重复来源只合并两类来源 | `phase7-regression-accepted/first-request-timings.json`；真实前台打开结果与确定性模拟合并单测分开，不要求首请求零丢失，也不伪造菜单操作 |
| BFCache / freeze / discard / replacement | 真正 `pageshow.persisted=true`；冻结/恢复后有业务事件；`tabs.discard` 触发两种正式 replacement 通知；新实例、基线和唯一动作可验证，包合法 | `phase7-platform-verified/platform-evidence.json`、`platform-1.zip`。迟到旧移除通知另由单测验证；不把该单测作为真实平台事件证明 |
| replacement 修复 | 旧实例在 await 前标记替换，避免 tabs 与 webNavigation 两条异步通知登记两个新实例 | 历史失败保留在 `phase7-platform-final` / `phase7-platform-diagnostic` 等目录；并发通知、迟到旧移除及新目标唯一性有单测与真实平台复验 |
| 导航恢复修复 | attach 等待期间的导航完成/丢弃恢复通知合并为一次后续检查，重新检查新文档注入；按 tabInstanceId 隔离，STOP 后不补注入 | 原先可能只有 network/runtime 就绪而 page/semantic 超时；真实丢弃恢复已复验，单测验证不自行轮询和截止保护 |
| 运行期和调试隔离 | 普通后台终止、同 profile 浏览器重启、实际 `chrome://extensions` 开发者模式 reload；同 URL 的两组并发请求跨恢复保持不同 debuggerSessionKey 和唯一 requestKey；真实 content script 伪造 STOP 被拒绝 | 主流程、平台专项、P1 停止整理中断；旧 tabId/ticket/分片、旧运行期和迟到结果用明确模拟反例补充，未将模拟当成浏览器复用 tabId 的实测 |
| 流与 worker | 分别证明 WS 发送、WS 接收、SSE 接收；专属 worker 和两个 iframe 业务已采集；共享 worker 两消费者确实完成请求但内部流量不入包；多 frame 无可靠来源 WS 排除 | `phase7-release/stream.zip`；真实正文 2 项在途、至少 4 项排队时 STOP，排队取消、迟到结果计数增加；扩展 detach，业务连接仍活着且不再接受证据 |
| 网络逐跳和正文 | 三条并发、每条三跳分别核对请求头、响应头、ExtraInfo、CDP ID/ordinal/requestKey 和最终正文；双侧正文及 HTTP/业务/网络结果分离；明确已接受在途请求关闭 | `phase7-release/network.zip`。大 POST 可能被浏览器正文缓冲拒绝或按预算排除，均显式保留原因；base64 解码、非法编码、双侧读取失败等分支由协议级故障注入单测覆盖 |
| 源时钟 | 页面 performance 与 Date.now 正负一天及再次倒退；原始 sourceTime、sourceClock、observedAt、sourceSeq 和 normalizedAt=null 保留，STOP 不受倒退影响 | `phase7-release/clock.zip`；只修改独立测试页时钟，不修改用户操作系统或扩展时钟；日志余量 120 秒不能消除一整天的源偏移，仍须用 observedAt/服务端 ID 并保留不确定性 |
| 真正离线导出 | 保存后关闭 fixture，阻断该 profile 网络，重开控制页实际下载；downloads.cancel 真实取消、摘要散列故障注入、生成中关闭、重开及重试 | `phase7-release/offline*.zip`、`export-attempts.json`。不同尝试单独保存；失败/取消/关闭不删唯一数据；未确认完成不显示成功 |
| 独立 Agent | 摘要→选定语义/网络/正文→requestId 日志→源码；事实/候选原因/反证/缺失分开，未读 rrweb | `phase8-agent/analysis.md` 与 `read-audit.ndjson`。页面注入文字首次未被选读，定向补读后没有改变任务或失败事实；不宣称全量提示注入防护 |

前轮回归入口与目录（非本次最终构建重跑）：

- `npm run test:browser` → `output/playwright/phase7-regression-accepted/`：49 项。
- `npm run test:phase7` → `output/playwright/phase8-scope/`：24 项（前轮 `phase7-release/` 的 21 项保留）。
- `npm run test:platform` → `output/playwright/phase7-platform-verified/`：6 项。
- `npm run test:p0` / `npm run test:p1` → `output/playwright/phase8-p0/`、`phase7-p1/`：20 / 24 项（P1 本次未重跑）。
- `npm run test:opening` → `output/playwright/phase8-opening/`：12 项，24 次打开的逐方式测量。
- 每个 acceptance.json 有具体断言、T 编号、场景类别、构建、系统、浏览器、权限模式、方法和状态。`scripts/audit-acceptance.ts` 仅汇总显式指定目录并逐包校验，不自动改写历史。

当前待验范围见上方第 7.5 组结论；前轮原生工具的连接失败及等待记录继续保留。

## 第 7 组续验（前轮历史，2026-11-16）

- 固定窗口：通过控制页窗口复选框选择两根，在点击开始前用 `tabs.create` 另建一页，实际根集合仍只有原两页；命名目标首次新建自动纳入，复用保持同一 tabInstance 和父引用。`phase8-scope/window-selection.zip` 校验通过，**API 新页不算原生 Ctrl/Cmd+T**。结合前轮“已存在未选命名窗口复用仍排除”，T15 本地组合已通过。
- 来源与首请求：`phase8-opening/first-request-timings.json` 每次保存唯一 marker、真实 tabs/webNavigation 来源、创建/确认/网络/基线时序及服务端到达。每方式 3 次，24 次均确认正确父实例、无重复登记，后续 `/api/echo` 请求全部采集；原生右键尚缺。服务端 ISO 与 CDP 时钟分别保留，不直接相减。
- 测试基础：所有浏览器入口按 manifest 名称与 background 脚本识别采集器 worker，避免首个 worker 属于其他扩展或启动过程；不修改生产权限。Chrome 125 的复验日志保留在 `phase8-chrome125-diagnostic/run.log`，不能把该环境发出的 `canceled_by_user` 当作完成实际用户取消验收，原因仍待独立验证。
- 原生辅助：分开确认快捷键、右键新页/新窗；每步要求实际操作说明与截图路径/人工观察，记录权限和实时状态；每次用全新目录防止复用旧确认。取消调试/F12 后以新赋值已保存、无新网络记录、界面降级及当前通道状态断言，修复此前读取旧状态即可通过的问题。完整路径尚未执行，仅首次等待点准备检查完成。

| 打开方式 | 试验次数 | 首请求捕获 | 就绪后请求采集 |
| --- | ---: | ---: | ---: |
| target=_blank | 3 | 0/3 | 3/3 |
| noopener | 3 | 0/3 | 3/3 |
| noreferrer | 3 | 0/3 | 3/3 |
| window.open | 3 | 0/3 | 3/3 |
| window.open 新窗口 | 3 | 0/3 | 3/3 |
| 鼠标中键 | 3 | 0/3 | 3/3 |
| macOS Cmd 点击 | 3 | 0/3 | 3/3 |
| 打开子页后同步关闭父页 | 3 | 0/3 | 3/3 |

这组通过指来源、后续采集与测量可复核；**不表示首请求被完整捕获**。保留已声明的 attach/注入前缺口，不刷新或重发请求来补齐结果。

## A0–A3 当前结论

| 阶段 | 结论 | 剩余边界 |
| --- | --- | --- |
| A0 能力验证 | 部分通过：真实采集、多根/来源、极快父关闭、基线、iframe、迟到截止和首请求时序已有证据 | 企业权限、原生右键/F12/许可组合及最低版本兼容仍未完成 |
| A1 范围与生命周期 | 部分通过：递归谱系、移窗/关闭、BFCache、正式 replacement、恢复/重载及严格 STOP 已实测 | 7.2 的原生窗口选择/快捷键组合与 7.3 菜单方式仍未完成 |
| A2 证据与本地闭环 | 本地适用场景通过：页面/语义/网络/错误、脱敏、保存、故障恢复和真正离线导出 | 截图条件不适用；跨源逐节点映射和无 frame 归属流保持明确限制；不外推生产 |
| A3 问题包与 Agent | 协议校验、引用闭包、异常恢复和本地独立按需分析通过；整体仍为部分交付 | 全部平台验收尚未收敛；生产日志/源码匹配和可选上传未接入，不作为本地失败 |

## P1 实施结果（第 4–6 组）

第 4–6 组均已完成，本轮新增 12 项完成任务，总进度 25/39。30 标签完整负载、近预算封包、失败重试及恢复证据分别保留，未把低频 fixture 的容量结果外推到真实复杂 MES 页面。

- P1 专项：`output/playwright/p1-accepted-final-v3/acceptance.json`，24 项真实浏览器断言通过；包含 native/role dialog、before 观察引用、语义预算、版本/日志来源、超过 5 秒的保存界面、三类真实 CDP session 共用并发，以及配额失败时实际下载已提交部分/恢复后重试。
- 完整回归：`output/playwright/p1-regression-v3/acceptance.json`，48 项通过；新采正常/恢复/中断/按钮下载 ZIP，`fixture-analysis.md` 为已知 fixture 协议脚本演练，不计独立 Agent 的 T49。
- P0 专项 `output/playwright/p1-p0-regression-v3/acceptance.json` 的 20 项断言通过。各目录的 `test-extension/build-info.json` 记录实际加载的构建；浏览器为 Chrome 157.0.8103.78，独立临时 profile，fixture host 预授权，生产 manifest 不变。
- schema/策略升版至 3.0.0/2.0.0，IndexedDB stores 布局与版本保持不变；旧 1.0/2.0 本地开发记录按版本清理，历史导出 ZIP 保留，未增加迁移层。

| 任务 | 已验证行为 | 证据与边界 |
| --- | --- | --- |
| 4.1–4.3 | 相关 form/dialog 读取；以前快照/观察时间；程序 value/checked/selectedIndex；原生及角色弹框；disabled/loading/校验提示；字段/属性/文本省略计数与 quality；STOP 恢复 setter/关闭观察器 | P1 浏览器逐项断言、before 引用篡改单测；动态控件暴露 rrweb 负数哨兵，节点关系清单现排除该非节点编号 |
| 5.3 | 有限来源配置、头/已观察 JSON/页面 meta、自定义日志标识、混合版本与每次来源、显式源码映射 | P1 浏览器 + 契约单测；人工映射不等于已经验证源码；无成功码协议保持 unknown |
| 5.4–5.5 | 稳定异常身份去重；多源候选组保留引用；不跨文档/标签合并；28,000 字符摘要与省略入口 | 大规模目标/标记/错误单测；错误候选组不是已确认故障数；文档未知的 Log 不合并 |
| 6.1 | root/OOPIF/worker 三个以上真实 CDP session 合计正文并发峰值为 2；等待数/字节有界 | P1 body-queue.zip；独立取消、旧 token 与 STOP 后等待项拒绝另有确定性单测 |
| 6.2–6.3 | STOP 立即截止；独立持久化意图；清理/排空/终结状态；事务挂起不竞争重试；事务中止/配额失败稳定批次重试；后台重建不恢复 STOP；只读导出已提交部分 | 慢写使用真实 IndexedDB 完成回调延迟 6.5 秒，不冒充物理磁盘慢写；配额失败为注入；另以读请求保活使真实 IndexedDB 写事务未提交，再通过 CDP ServiceWorker.stopWorker 终止 worker；恢复不重新采集且 interrupted-stop.zip 可校验。扩展重载及其他平台矩阵仍归第 7 组 |
| 6.4 | 分片中 STOP、重组/队列/硬预算超限安全截止；旧流不能无基线续写；不保存被拒绝正文的 bodyRef，拒绝事件不占已保存序号 | 专项单测与合法问题包校验；拒绝数据不会被静默补成已保存 |

### P1 容量测量（已完成）

硬件：Apple M1 Max、64 GiB RAM、macOS arm64。该机器同时进行开发及其他回归，不是空载专用性能机。

- 近默认 200 MiB 接受预算的**合成封包**：`output/playwright/p1-export-capacity-v3/measurement.json`；输入 190.6 MiB（95.3%），205 个完整 JSON 正文，ZIP 110.5 MiB；封包 5.29 秒、独立校验 1.77 秒。独立 Node 导出进程 250ms 外部采样峰值 RSS 770.9 MiB、CPU 117.9%（单核 100%）。该结果不是浏览器端同规模采集或 600 MiB ZIP 防护上限的容量证明。
- 正式逐级浏览器负载：`output/playwright/p1-capacity-final-v3/`；每页每 15 秒程序赋值并请求一次接口，启用页面计时延迟和 longtask 观测，保留正常后台节流。1/10/30 标签分别完成 60/120/1800 秒负载（总时长含停止、读取与导出为 60.125/120.649/1824.371 秒）；记录扩展队列、正文预留、接受/持久化记账字节、各页 heap/延迟及本任务 Chrome 进程树 CPU/RSS。RSS 求和可能重复计算共享页，不能当作操作系统唯一物理内存。
- 初次 10 秒间隔负载 `p1-capacity-v3/` 的 1/10 阶段完成，30 标签约 410 秒后因实现修复主动结束；见 interruption.json，不计 30 分钟验收。其原 environment 的后台节流说明已在该文件更正。
- 固定 **每 CDP collector 5,000 条请求链** 是独立覆盖上限：5,100 个合成请求单测只接受 5,000 链并记录缺口，超限不再累积空链；不能据此宣称无限期持续采集。30 分钟低频负载不会触达此阈值。

详细结果：`output/playwright/p1-capacity-final-v3/report.json`，原始每轮数据为 `samples.ndjson`，三个 ZIP 都通过当前校验器。每次请求均 finished、响应正文 captured 且文档映射非空。

| 标签 / 负载时长 | 请求数 | 接受记账 MiB | 页面赋值+fetch p95 ms | Chrome 树 RSS 采样峰值 MiB | Chrome 树 CPU p95（单核100%） | ZIP MiB | 封包+校验+写文件 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 / 60 秒 | 4 | 0.168 | 7.2 | 987.8 | 167.6% | 0.026 | 40 |
| 10 / 120 秒 | 80 | 3.294 | 16.2 | 2145.2 | 266.6% | 0.451 | 170 |
| 30 / 1800 秒 | 3600 | 137.122 | 42.9 | 5163.4 | 163.3% | 24.602 | 6961 |

30 标签阶段：CPU 采样最大 357.9%；Chrome 树 RSS 从 4604.3 增至 5163.4 MiB；页面报告 heap 最大约 5.93 MiB。页面 100ms 定时采样的平均延迟 1.09ms、最大 621.4ms；共观察 16 次 longtask、累计 2106ms。没有同规模无扩展对照，不能将这些值解释为扩展净开销。

每标签正文峰值在途 1 项、预留 1 MiB；本场景为低频请求，并发上限 2 另由 P1 三类 session 专项证明。Journal 合计记账峰值 1,176,053 字节；采样排队峰值 733,967 字节、在途峰值 471,355 字节，均低于 16 MiB 队列预算。接受吞吐约 78.0 KiB/s，接口吞吐 2 次/s；总接受 137.1 MiB 未触发 200 MiB 硬截止，100 MiB 软提醒按预期出现。

30 标签缺口只有 soft_tab_limit、initial_coverage_gap、screenshots_disabled、worker_scope_limit、soft_budget_reached；没有正文读取或通道失效。1 标签启动另有 frame_not_permitted，见原始记录，不以 0 缺口宣称完整浏览器覆盖。每 collector 的负载最多 120 条请求，远低于 5,000 链限制。

实际支持范围是本机、本浏览器、每页每 15 秒一次小 JSON 请求与程序赋值的 30 分钟场景；没有覆盖 30 个真实复杂 MES 页面、长时间高频请求或最大单正文并发。容量构建绑定 environment.json 中 hash；期间新增的只读救援、失败序号保护、错误关系校验等使用最终构建的功能专项和契约测试验证，未将后续构建声称为重复完成同一长测。

- 当前测量未证明需要引入增量 ZIP 或额外存储权限；保留现有封包方式，不声明零开销。

## P0 实施结果

对应 OpenSpec 变更 `complete-evidence-collector-acceptance` 的任务 1.1–3.4、5.1–5.2，共 13 项。本轮没有完成整个变更的 A0–A3 验收。

| 范围 | 实现与证据 | 尚未覆盖 |
| --- | --- | --- |
| 敏感区域 | 普通 id/data-*、允许字段、父容器文本统一屏蔽；无关键词哨兵跨桥、数据库、ZIP 检查；允许业务精度仍为 `3.00` | 真实 MES 的现场规则配置 |
| 脱敏失败 | 控制页及页面分别检查选择器；非法 JSON/超限正文明确排除 | 截图继续停用，不计 T35 截图执行通过 |
| 通道状态 | 四个必要通道独立就绪、10 秒期限、父/子 session 失败隔离；实际控制页显示部分采集 | 原生 F12/用户取消调试的专项验收 |
| 部分启动 | 混合授权/关闭根、全失败诊断、格式错误单测；正常 UI 在权限请求被测试桩拒绝后仍启动已有授权根 | 原生权限对话框及企业策略；测试桩不是平台授权验收 |
| 文档/网络归属 | 顶层、同 URL 同源、跨源 OOPIF、嵌套同源、动态移除、策略排除、SPA 和完整导航实测；每个声明覆盖文档有基线引用；CDP 采用本扩展隔离上下文票据 | 不能确认的跨源逐节点关系保持 unknown；真实 BFCache/replacement 待测 |
| 契约与引用 | JSON Schema 生成静态校验；nodeId=42 跨标签及同文档重启流隔离；hash 正确但跨目标/文档/调试会话、缺基线/必要文件、错误候选及正文字节的反例拒绝 | 该行是 P0 历史范围；版本/日志配置、错误归组、摘要和资源进展见本轮 P1 记录 |

回归中修正了两个被新检查发现的问题：OOPIF 初始空 URL 的过早排除，以及后台恢复时同一 Chrome document 的新旧 recorder 基线串位。1.0 本地开发记录在后台初始化时按版本清理；历史导出文件保持不变，新格式重新采集。

## A0 初始能力记录（历史）

实际取得 rrweb Meta/FullSnapshot、普通输入、MAIN world 程序赋值、短暂 toast、对话框及 iframe attach 增量。同源 frame 由顶层统一录制，子 frame 只增加语义采集；跨源 frame 使用 rrweb 协作录制。跨源节点重映射无法全部可靠对应 Chrome document，显式保存 `subjectContext=unknown_or_multiple` 和相关模式说明。

根/子/孙来源、双窗口、移窗、父关闭、未完成请求关闭和严格全局停止均有真实扩展证据。重复 START 不重复 recorder；停止后的页面轮询与程序赋值不新增业务证据；迟到 attach/body 的代数检查另有确定性测试。

**首请求测量：5 个新建后代，最早唯一标记 API 捕获 0 个。** 这些请求发生在来源确认、attach、Network.enable 之前；记录 createdObservedAt、lineageConfirmedAt、ready/baseline 时间和 initial gap。初始覆盖未通过刷新、重发、暂停页面或全浏览器预录补齐。后续正常请求与响应可采集。此结果是当前构建的明确覆盖限制。

Playwright 在后台标签触发打开动作时，曾观察到 `tabs.onCreated.openerTabId` 与 `webNavigation.sourceTabId` 冲突。实现拒绝此歧义目标，保留可手动添加的提示；实际前台点击的普通新标签、window.open、noopener、noreferrer、新窗口、中键、Cmd 点击已通过。没有通过 URL 或最近激活标签推断来源。

普通 service worker 强制终止后，同 browserRunId 对账、重建基线和不补采无关目标已验证。整个浏览器关闭并以同一 profile 重启后，新 browserRunId、旧会话 INTERRUPTED、旧数据可导出已验证。初始测试中，命令行临时加载的扩展调用 `runtime.reload()` 被移除；本轮已另用实际开发者模式 reload 按钮完成验证，见上方平台记录。

## 性能对照

以下表格保留初始 1.0 构建的历史测量；本轮数据另存 `output/playwright/p0-regression-v2/performance.json`。同一 fixture、单标签，保留 1,800 个静态段落；30 次程序赋值与 200 个节点文本更新，每次等待两个 animation frame。先关后开采集，历史原始值见 `output/playwright/performance.json`。

| 观测 | 关闭采集 | 开启采集 |
| --- | ---: | ---: |
| 单轮平均时长 | 33.00 ms | 32.71 ms |
| 单轮 P95 | 35.00 ms | 34.90 ms |
| 页面 CDP TaskDuration 增量 | 0.148 s | 0.179 s |
| 页面 CDP ScriptDuration 增量 | 0.0008 s | 0.0848 s |
| 页面 JS heap 观测 | 1.57 MB | 5.55 MB |

该轮 network ready 约 14 ms，首基线约 79 ms；保存 153 个事件、约 2.52 MB（包含接受/索引开销）。超 128 KiB 的真实 rrweb 基线已完整分片重组、封包校验。性能为单次顺序对照，包含自动化的节流差异；页面 CDP 指标不等于整个浏览器/扩展 CPU 或 RSS，不能据此宣称零开销、30 标签容量或长期运行已达标。

## 规格验收矩阵

“单测”表示确定性边界检查；“待实测”保留平台行为/人工操作验收要求。

| 编号 | 状态与证据 |
| --- | --- |
| T01 | 真实浏览器通过：双窗口只选 A/B，未选页无 recorder、业务证据和秘密内容 |
| T02 | 部分：窗口复选框固定两根，选择后 API 新页不追加已实测（phase8-scope）；原生 Ctrl/Cmd+T 组合仍待 7.2。 |
| T03 | 真实浏览器通过：A→C→D，幂等单流 |
| T04 | 部分：新窗后代纳入、窗内另建无关页排除已实测；完整原生窗口选择组合仍待 7.2。 |
| T05 | 真实浏览器通过：关闭 A，C/D 继续 |
| T06 | 通过：真实关闭中间节点，存活叶子继续且历史父引用保留；见 scope.zip。 |
| T07 | 通过：实际移入普通窗口后关闭整窗，多个成员分别截止，其他根继续。 |
| T08 | 通过：移窗后保持 captureGeneration、文档/流，实际 7.777 赋值保存并通过引用校验。 |
| T09 | 通过：同 URL 未选页及其新建后代无授权/业务证据，不按 URL 纳入。 |
| T10 | 真实浏览器通过：开始前旧子页、manual_add 前旧子页/后新子页 |
| T11 | 通过：真实 window.open 后同步关闭脚本打开的父页，子页仍登记、建立基线并继续；迟到来源另外有模拟单测。 |
| T12 | 通过确定性模拟：同一后代重复两类来源通知只保留两类来源、只登记一次；真实重复命令回归保持通过。 |
| T13 | 真实浏览器通过：普通 target=_blank、noopener、noreferrer、window.open |
| T14 | 部分：中键/Cmd 点击通过；实际右键菜单新页/新窗尚未完成，不以 window.open 代替。 |
| T15 | 本地组合通过：既有未选命名窗口复用仍排除；选中根首次命名新建纳入，再次复用保留同一实例和父引用；见 phase8-scope/window-selection.zip 及前轮主流程。 |
| T16 | 已测量：phase8-opening/first-request-timings.json 按 8 种方式各 3 次，24 次首请求捕获 0 次、后续请求均采集；逐次真实来源/就绪/服务端到达可查。尚缺原生右键方式，不宣称全覆盖。 |
| T17 | 真实浏览器通过：慢请求关闭后 incomplete_target_closed |
| T18 | 迟到 body/attach 单测通过；真实关闭后无尾部正文；截图策略停用 |
| T19 | IndexedDB 原子批次单测通过：截止前接受的数据可完成落盘 |
| T20 | 通过本地适用矩阵：WS/SSE、worker/iframe、轮询/赋值、排队/迟到正文在 STOP 后不追加业务；扩展连接释放，业务连接继续。 |
| T21 | 真实浏览器通过：全部目标关闭后不采新无关页面，等待手动结束 |
| T22 | 真实浏览器通过：刷新形成新文档和基线，旧票据失效 |
| T23 | P0 实测 history/hash 后实际 document 和 recorderStreamId 保持，完整导航另建基线 |
| T24 | 通过本次平台：真实 pageshow.persisted=true；恢复后新流/基线可解析，单次赋值无重复动作；冻结/恢复另有实际 CDP 生命周期记录。 |
| T25 | 通过本次平台：真实 tabs.discard 触发 tabs.onReplaced 与 webNavigation.onTabReplaced；仅一个新实例、恢复单流、合法导出；迟到旧移除另有单测。 |
| T26 | phase11 网络专项补齐新 frame 首次 Document/Fetch、同进程与 OOPIF 未授权排除；P0 同 URL/跨源/嵌套与基线回归通过，跨源逐节点映射仍 partial。 |
| T27 | P1 真实浏览器逐项通过无 input/change 的 value、checked、selectedIndex；停止后属性包装恢复及不再发包 |
| T28 | P1 逐项验证 native dialog open/close、role dialog 祖先显隐、disabled/loading、原生校验提示及异步提示时间；预算省略可见 |
| T29 | 同号 nodeId=42 跨标签及同标签新旧流隔离与错误引用拒绝已通过契约测试 |
| T30 | 通过：并发多跳逐项匹配回归；phase11 补齐 SW not_expected、SW→网络混合跳、空 hop 和未知屏障，双侧头不串位。 |
| T31 | 真实浏览器通过 HTTP200 业务失败、HTTP500、网络失败三层区分 |
| T32 | 通过适用分支：text/plain POST、XSSI JSON、gzip 解码限额及显式 2 MiB 配置有本地与公开 web.dev 实测；字节/引用可核对。缓存、协议与编码错误分别报告；未取得的历史正文不能补回。 |
| T33 | 通过适用范围：分别有 WS 收发、SSE 接收及 STOP 结果；多 frame 无可靠 WS 来源明确排除，不宣称该来源已捕获。 |
| T34 | 通过：同源已选/未选页共用真实 SharedWorker，两个请求完成但共享内部标记未入包；共享内部采集能力仍不支持。 |
| T35 | 条件不适用：截图固定 unavailable/disabled_privacy；P0 检查零 CDP 截图调用，未实现 captureVisibleTab 回退；不计截图执行通过 |
| T36 | 部分：降级/保留拒绝有单测和 P0 UI 验证；实际 F12 与用户取消调试尚待 7.5。 |
| T37 | 通过实际权限状态下的未授权导航返回、根撤权与后台恢复；phase9-permissions-final 保留无业务哨兵、新基线和成员连续性证据。撤回后会话内原生重新授权仍归 7.5 待测。 |
| T38 | 按用户新策略通过：普通文本/输入/URL/认证头/令牌原值存在，密码输入、显示密码、JSON/表单/URL/Basic 密码被保护；P0 显式额外选择器另有回归。非标准登录字段须现场核对，不再宣称通用凭据全部脱敏。 |
| T39 | 真实大基线分片与导出校验通过；重复/冲突/队列上界/空片攻击有单测；停止时片段丢弃显式 gap |
| T40 | 通过本地矩阵：普通后台终止恢复、同 profile 浏览器重启中断、实际开发者模式 reload 中断；停止整理中的真实事务/后台中断由 P1 验证。 |
| T41 | 通过：关闭 fixture 并阻断网络后重开控制页实际下载；真实 cancel、生成失败注入、重试和逐包校验均通过。 |
| T42 | 通过恢复隔离矩阵：同 URL 两组并发请求在后台恢复前后具有唯一 requestKey、不同 debuggerSessionKey，头/正文不串位；F12 属于 T36 待测范围。 |
| T43 | 部分：原始 manifest、独立预授权 profile 下，实际 API 撤权、子 frame 隔离、混合根和全失败通过（phase9-permissions-final）。原生请求/拒绝/撤回/重新授权组合仍待 7.5，预授权和 RPC 不代替弹窗。 |
| T44 | 通过：先取得专属 worker、同源/OOPIF 业务证据，再验证停止后不追加；无可靠文档身份仍保留 unknown。 |
| T45 | 通过本地与模拟组合：真实 content script 伪造控制 STOP 被拒绝；重复 START/STOP、旧运行期、复用 tabId 的旧 ticket/分片、启动中 STOP 和晚到结果被拒绝。 |
| T46 | 通过独立测试页：performance/Date.now 偏移与倒退不改写观察时间/源序号，不影响 STOP；normalizedAt=null，日志余量和关联 ID 解释边界保留。 |
| T47 | 真实包的未匹配源码为 unresolved、未知版本为 unknown；fixture 版本来自响应头 |
| T48 | 本次最终构建 23 个新包全部通过强化校验，见 phase11-validation.json；phase9/phase8 历史包保留各自构建及策略，不改写成新结果。 |
| T49 | 通过限定本地演练：独立 Agent 读摘要、所需事件/正文、日志和源码，未加载 rrweb；定向补读页面指令文字后任务和事实不变，非全量注入防护证明。 |
| T50 | 通过：控制页关闭不影响录制；生成中关闭后的状态明确为未确认完成，重开可再次导出且唯一数据保留。 |

## 具体限制与接入项

1. 截图因动态页面像素脱敏无法保证而停用；当前没有截图附件。页面结构/状态/网络证据仍可使用。
2. rrweb 覆盖开放 Shadow DOM，Canvas 和 closed Shadow DOM 内容不承诺。跨源 iframe 逐节点 Chrome document 映射是部分覆盖，缺失不可猜测。
3. WebSocket/SSE 仅采集能确认归属的有界 JSON 文本；二进制、自由文本或多 frame 的无归属 WebSocket 明确排除。
4. 最早请求和已存在连接不保证捕获。正文 getResponseBody 可一次返回完整数据，保存限额不等于浏览器仅读取前 N 字节。
5. 真实域名/API 规则、业务成功码、字段白名单、敏感区域、构建到源码映射、企业权限、保留期限和可选上传接口均需现场配置。当前未接入真实 MES/日志/代码平台。
6. 右键菜单、F12/取消调试与原生权限组合仍在上表保留为验收缺口；BFCache 和正式 replacement 已取得本轮平台证据；长时容量仅在上述明确负载内完成。当前可运行闭环不构成规格全部项目的验收结论。

平台核对参考：[Chrome Debugger](https://developer.chrome.com/docs/extensions/reference/api/debugger)、[Scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[rrweb 跨源 iframe](https://rrweb.com/docs/recipes/cross-origin-iframes)、[Playwright 扩展测试](https://playwright.dev/docs/chrome-extensions)、[Chrome for Testing 版本信息](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json)。

## 2026-11-18 离线回放接口面板

独立 Chrome 在断网状态下通过 `npm run test:replay`。同一份模拟录制分别以 ZIP 和文件夹导入，验证了查询参数重复键、表单解码、请求和响应正文、HTTP 状态、附件缺失提示，以及播放、暂停、进度条回退和切换页面。模拟响应晚于最后一帧，播放结束后可查看完整正文。

使用已有本地录制 `mes-evidence-2d1e0076-0abb-4a31-b061-49bbf742ea15` 核对，`web.dev` 页面显示 5 条请求，`GET /baseline` 的 HTTP 200 与响应附件可读，`POST /_d/dynamic_content` 分别显示请求正文被策略排除、响应正文不可用。回到起点显示 0 / 5，切换到同包 Google 页面显示 0 / 0。

路径筛选与请求定位已在 ZIP 和文件夹入口通过浏览器回归。测试从回放起点搜索整段录制，验证大小写、路径片段、域名和查询参数排除、清空筛选和跨页面隔离。鼠标与键盘分别定位到两条请求，回放 iframe 中的工单文字与各请求发起时的页面一致。早于页面首帧的请求定位到首个完整快照。

同一份 `web.dev` 录制中，搜索 `BASELINE` 匹配两条，搜索 `/baseline` 匹配一条。播放中点击该请求，回放暂停在 00:07.3；在末尾单点「详情」可以查看 HTTP 200，进度保持在末尾。390 像素宽窗口下也能定位请求。

## 2026-11-18 现场录制布局与点击坐标

现场包第 3 段共 1167 个 rrweb 事件。视口从 1270 × 911 在约 6.62 秒时变为 1634 × 855。该段在快照及后续节点新增中共引用 35 个不同外部样式表，包内没有对应的 CSS 正文。本机提供的 EBR 源码目录中未找到同文件名的部署样式。旧包的原始排版仍缺少现场样式进行逐项比对。

在独立 Chrome 中断网打开现场 ZIP，拖至 01:14，修复前鼠标停在 (0, 0)。同步重建使用实际 DOM 后，原包最后一次点击（约 45.534 秒）显示在 (1584, 116)，与保存的坐标一致，当时的接口计数为 25 / 27。播放器在缺样式时按 rrweb 节点 ID 标记最近点击的元素。现场包还触发浏览器的离线媒体播放提示，本次核验范围为布局、定位与接口面板。

布局专项用实际录制脚本捕获静态和延迟加载的外部 CSS，替换按钮节点后再点击。断网回放时，按钮矩形与原始 CSS 像素坐标一致，在两种窗口宽度下，回放鼠标均落在缩放后的按钮内部。超过单包预算的多张样式表在保留完整首帧后分条发送。针对仅有 CSS 引用的样本，补入同路径同文件名的本地样式后恢复了按钮原位置。问题包未被改写。

独立 WebKit 也通过上述布局专项。在现场包中，使用进度条的 End 键和控件的点击事件定位到 01:14，得到相同视口、点击坐标和 25 / 27 条请求。WebKit 自动化对进度条的物理鼠标点击未通过命中检查，此项不能视为 Safari 原生手动拖动验收。
