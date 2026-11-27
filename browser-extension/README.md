# 浏览器采集助手

按 `MES_Browser_Evidence_Collector_Development_Spec.md` 实现的 Chrome Manifest V3 扩展。手动选择当前 Chrome 配置中的标签，记录根标签及可信新建后代的页面、操作、请求和错误；证据在扩展 IndexedDB 内保存，可离线导出 ZIP。关闭控制台不会停止录制。

项目目前是可运行的本地版本，真实 MES 域名、成功码、版本接口、源码映射及上传服务尚未配置。截图固定停用，跨源 iframe 的统一 rrweb 流对部分节点保留 `unknown_or_multiple` 归属，不能解释为完整像素或逐节点跨 frame 映射。验收范围和未验证场景见 [验收记录](docs/acceptance.md)。

## 构建与安装

插件位于平台仓库的 `browser-extension/`，独立构建和发版。需要 Node.js 22.12.0+。从仓库根目录执行下面的命令。

```sh
cd browser-extension
npm ci
npm run check
```

在 Chrome 打开 `chrome://extensions`，开启开发者模式，点击“加载已解压的扩展程序”，选择本项目 **dist** 目录。工具栏扩展图标会打开控制台。API/语法技术下限为 Chrome 125，当前已验证运行范围为 Chrome for Testing 157.0.8103.78（macOS arm64）。125 尚未通过兼容验收，不承诺所有 125+ 版本；详见 [支持范围与现场接入清单](docs/mes-onboarding.md)。生产 manifest 不申请全站访问，开始前会按策略请求业务站点权限。

## 在插件中向 Agent 提问

平台与插件共用[接口契约和合成样例](../contracts/browser-extension/v1/README.md)。准备好仓库根目录的 Python 开发环境 `.venv` 和 Playwright Chromium（或用 `MES_TEST_CHROME` 指定本机 Chrome for Testing）后，在插件目录运行 `npm run test:agent`。测试会启动独立浏览器和本地合成平台服务。

打开控制台的「询问 Agent」，首次粘贴 Enterprise Agent 的内网 HTTP 地址（例如 `http://agent.intra:8080`），点击「用系统账号登录」。在系统页面登录并确认授权后，从列表选择业务应用即可发消息。插件会记住系统地址和上次选择的应用。列表只显示当前账号获准使用、已激活且开启浏览器插件入口的应用。

在「站点设置」保存页面的业务应用和绑定范围，并开启悬浮助手。单击页面上的紫色图标打开阅读浮窗，再次单击或点「−」即可收起。收起后草稿和正在接收的回答都会保留。拖动图标或浮窗标题栏可以移位。

发送问题后，输入框右侧的箭头会变成「停止回答」方块。点击方块可取消自己发出的这轮任务。任务结束后恢复发送按钮，输入框中尚未发送的追问会保留。

右键图标或长按半秒打开「本页持续采集」，再选择开始或停止。键盘可在图标上按 Shift+F10，浮窗标题栏也有同一菜单。采集中图标显示计时。浮窗首次启动采集使用当前站点的默认策略，同一业务应用和采集策略覆盖的其他标签页可以分别加入、停止。控制台的「结束持续采集」作用于整场录制。需要自定义接口范围时，可先从控制台启动。

本版为解压安装包固定了扩展 ID。从早期开发版升级时，Chrome 可能将它识别为另一个扩展。需要保留旧录制时请先在旧版导出，再加载新版。

## 使用

1. 打开需要采集的网页。点击扩展图标，按“窗口 → 标签”勾选明确根标签。可以按名称或网址搜索，全选只作用于当前结果。
2. 环境取自站点关联；未关联也可以采集。检查“采集范围与权限”。开始时冻结策略；跨域 API/iframe 需提前加入规则。
3. 点击“开始采集”并授予站点权限。Chrome 可能显示调试提示。准备中、部分采集、每通道状态和覆盖缺口均显示在控制台。
4. 在网页中按正常流程操作。新创建的可信子孙标签自动加入；相同 URL、已有命名窗口、普通新建标签不作为来源证明。
5. 选择已纳入目标并“添加时间标记”，或通过“添加标签”明确增加根节点。添加根不会追溯纳入它之前打开的子页。
6. “结束采集”先关闭所有接受入口，再保存和清理。可直接预览数据和导出 ZIP。本地记录可按时间、环境或记录编号搜索。

关闭某标签只停止该标签；存活子孙继续。全部目标关闭后，仍需手动结束。已保存历史可反复导出；不会自动上传或删除。卸载扩展会清除本地数据库。历史记录的“删除”只删除所选会话的本地证据，需要在界面确认。

## 页面回放与接口对照

在插件目录运行 `npm run build:replay`，然后用 Chrome 打开生成的 `release/MES-rrweb-replay.html`，选择导出的录制 ZIP 或已解压的录制文件夹，再选择录制页面。播放器可断网使用，也可以单独复制到另一台电脑上。

播放或拖动进度条时，「接口请求」按所选页面的时间逐条出现，最新请求排在上方。在「筛选接口路径」中输入路径片段（如 `/orders`），可搜索当前页面整段录制，匹配时忽略大小写。尚未发起的请求也会列出。清空筛选后恢复按进度显示。

点击请求行中的时间、方法或路径，播放器会跳到该请求发起时的画面，暂停并展开详情。若请求早于首帧，则跳到最早可用的页面快照。单点右侧「详情」可在当前位置查看完整 URL、查询参数、请求正文、HTTP 状态和响应正文。向前跳转可以看到已经返回的结果，向后拖动会恢复当时的状态。正文截断、未采集或附件缺失时会显示原因，密文按包内保存的文本展示。最后一帧之后才完成的请求，可在时间轴末尾查看。

录制器把浏览器能读取的外部 CSS 规则保存在 rrweb 事件中。缺少样式时，播放器提示当前页面缺少的样式表数量，并用橙框标记最近点击的元素。点击坐标始终按录制视口回放。打开旧包后，可用「补入同版本样式目录」选择现场前端发布目录，保留 `css/`、`ebr/css/` 等部署路径与完整文件名。补入操作只影响当前回放。跨域不可读的样式、独立字体和图片仍可能影响布局。

使用 `npm run build:replay` 重新生成离线 HTML，使用 `npm run test:replay` 验证播放器，使用 `npm run test:replay-layout` 验证录制与断网回放中的元素位置和点击坐标。可通过 `MES_TEST_CHROME` 指定测试浏览器。

## 策略配置

控制台提供 JSON 编辑器和模拟 MES 示例。默认只允许已选页面的明确 origin，不支持用任意 URL 相似度扩大范围。

| 字段 | 含义 |
| --- | --- |
| `pageOrigins` | 允许的页面/iframe 完整 origin，如 `https://mes.example.com`，包含实际端口 |
| `apiRules` | 独立 API origin 和 `pathPrefix`；只保存匹配的请求类型 |
| `requestTypes` | 默认 Fetch、XHR、Document、WebSocket、EventSource |
| `allowedInputNames` | 默认 `["*"]`，普通输入值全部保留；密码输入始终保护。可手动改为指定字段列表 |
| `allowedQueryKeys` | 默认 `["*"]`，URL 参数全部保留；密码参数和 URL 用户信息中的密码仍保护 |
| `sensitiveSelectors` | 需要整块屏蔽的区域；建议现场补充账号、认证、隐私区域 |
| `maskAllText` | 对 DOM 可见文本全面掩码；默认保留业务文字并处理已识别的秘密模式 |
| `businessRules` | origin、路径前缀、JSON `codePath`、明确的 `successValues`；未匹配时业务结果为 unknown |
| `correlationSources` | 最多 32 条来源：已有响应头、已脱敏 JSON Pointer、明确 `meta[name="..."]`；分别指定字段与组件，不主动发请求 |
| `sourceMappings` | 环境 + 组件 + 构建 ID → 源码快照；人工配置仅为 configured_unverified，冲突/缺失为 unresolved |
| `captureStreaming` | 默认关闭消息内容；开启后只保存有界 JSON 文本消息，二进制/自由文本排除 |
| `budgets` | 标签数、正文、DOM 基线、IPC、队列、会话容量、正文并发与时长提醒 |
| `logTimeMarginSeconds` | 后续日志时间检索余量，默认 120 秒 |

默认：10 标签软提醒 / 30 硬上限、30 分钟提醒、128 KiB IPC、8 MiB 基线、1 MiB 单侧正文、16 MiB 队列、100 MiB 软提醒 / 200 MiB 会话预算。正文超限排除，不输出破损 JSON；基线/传输依赖丢失会停止受影响流并记录 gap。截图目前为 `disabled`：DOM 脱敏不能保证截图像素安全，不回退到窗口活动标签截图。

按用户确认，默认策略 `policyVersion=3.0.0` **仅保护登录密码**。普通页面文本、输入值、DOM 属性、URL 参数、Cookie/Set-Cookie、Authorization Bearer、JWT、令牌和业务字段保留原值。`maskAllText=false`、`sensitiveSelectors=[]`；`data-sensitive` 不再默认屏蔽。密码输入、autocomplete 密码字段及 password/passwd/pwd/pass 等明确密码字段仍保护，HTTP Basic 仅替换密码部分。

正文支持 JSON、精确 XSSI 前缀 `)]}'` 后换行的 JSON、URL 编码表单和 text/plain；普通值不做通用脱敏，自由文本也可保存，密码仍在持久化前处理。压缩响应按解码后大小执行预算；若需要保存约 1.42 MB 的 web.dev 动态响应，在“采集策略与权限 → 策略 JSON”将 `budgets.bodyBytes` 改为 `2097152`（2 MiB），再开始新录制。默认 1 MiB 下会明确标记超限排除。

## OpenSpec 协作

平台与插件共用[仓库根目录锁定的 OpenSpec](../package.json)。先在仓库根目录运行 `nvm use` 和 `npm ci`，然后在插件目录运行以下命令：

```sh
npm run openspec -- --version
npm run openspec -- list
npm run openspec -- validate --all --strict
```

中文与项目约定见 [OpenSpec 配置](openspec/config.yaml) 和 [AGENTS.md](AGENTS.md)。提案、规格、设计、任务与沟通使用简体中文；模板结构标题及规范语法标记保留英文，符合 [OpenSpec 多语言规则](https://github.com/Fission-AI/OpenSpec/blob/main/docs/multi-language.md)。

Codex 的 `$openspec` 入口和各工作流均位于[共享技能目录](../.agents/skills/)。也可以直接指定工作流：

```text
$openspec-propose 补齐 BFCache 恢复场景的验收
$openspec-apply-change <变更名称>
$openspec-archive-change <变更名称>
```

另外提供 `openspec-explore`、`openspec-update-change` 和 `openspec-sync-specs`。如果当前会话未显示新增技能，重新打开项目会话后使用。

本次安装保留了用户目录内旧版 OpenSpec 命令。将来运行官方 `init` / `update` 前应检查其全局旧命令清理行为，避免影响其他项目。

## 模拟 MES 与测试

```sh
npm run fixtures
# 打开 http://127.0.0.1:4317
# 控制台选择该标签，并点击“使用本地示例”
```

模拟页提供版本冲突、程序赋值、短暂提示、弹框、同源/跨源 iframe、子孙标签、新窗口、未完成请求、重定向、网络错误、密码保护与令牌保留、WebSocket/SSE 和 dedicated worker。它只监听本机测试使用的 4317/4318 端口；结束终端进程即可关闭。`npm run test:network` 的专项 fixture 使用 4517/4518，自动关闭。

```sh
npm run typecheck
npm test
npx playwright install chromium
npm run build
npm run test:browser
npm run validate:package -- output/playwright/sample-evidence.zip
```

浏览器测试用独立临时配置，结束时仅关闭该配置及测试服务。生产扩展不改权限；测试会复制构建并仅预授予两个本地 fixture 站点，以避开操作系统权限对话框。可用 `HEADED=1` 显示测试浏览器；`MES_TEST_CHROME=/absolute/path/to/Chrome-for-Testing` 选择对应版本；下载目录自定义时设置 `PLAYWRIGHT_BROWSERS_PATH`。`MES_TEST_OUTPUT` 可以指定新的产物目录以保留历史结果；P0 专项运行 `npm run test:p0`。自动化产生的 `output/playwright/` 包、截图和 JSON 为模拟数据，不是生产验收。

控制页只有页面、操作、网络、错误四个通道都就绪才报告完整采集；部分失败显示“部分采集”和通道原因。未获得新增站点权限时，已选且已有权限的有效根仍可开始；全部根失败会保留可导出的诊断会话。截图因像素隐私固定停用。撤回主机权限会立即停止受影响标签的旧采集；子 frame 撤权时，该标签在仍授权范围内重新建立基线，其他根继续。

采集包格式为 4.0.0，记录与事件仍为 3.0.0。新导出省略旧版问题表单，校验器也支持已有的 3.0.0 ZIP。记录及事件契约为 3.0.0（策略 2.0.0）。新校验器检查观察引用、文档基线和跨记录身份，旧 1.0/2.0 开发记录在后台初始化时清理并重新采集；磁盘上已导出的历史 ZIP 不变。`npm run schema:generate` 从发布的 JSON Schema 生成静态校验代码，常规测试和构建也执行生成步骤。

只有用户另外配置 `sensitiveSelectors` 时才额外屏蔽匹配区域；默认仅密码保护。无效选择器在控制页拒绝，并在页面注入时再次检查。已知文档/节点通过已登记身份对应；未知关系不猜测。具体字段、边界与验收记录见 `docs/protocol.md` 和 `docs/acceptance.md`。

## 代码入口

| 目录 | 职责 |
| --- | --- |
| `shared/` | 身份/事件/正文契约、策略校验、跨通道脱敏 |
| `extension/background/session/` | scope、generation gate、控制命令、文档票据、停止和恢复 |
| `extension/background/lineage/` | 最小生命周期候选、同源序号授权、递归纳入 |
| `extension/background/cdp/` | flat 子 session、Network/Runtime、重定向 ExtraInfo、正文并发 |
| `extension/content/`、`extension/page/` | 隔离侧路由和 MAIN world rrweb/语义观察 |
| `extension/storage/` | IndexedDB、原子分片/checkpoint、保存错误状态 |
| `extension/export/` | 摘要、ZIP、清单/hash/流/引用校验 |
| `extension/ui/` | 目标选择、状态、标记、历史、脱敏预览、下载 |

消息和恢复设计见 [内部协议](docs/protocol.md)；问题包阅读见 [Agent 消费说明](docs/agent-consumption.md)。完整原始需求保留在开发规格中，未通过的验收项不会因实现了代码就标为通过。

P1 专项使用 `npm run test:p1`，覆盖语义范围/时间、程序属性、弹框、关联来源、慢保存与跨 iframe/worker 的每标签正文并发。`npm run test:capacity` 执行 1/10/30 标签、其中 30 标签持续 30 分钟；`npm run test:export-capacity` 为接近默认会话预算的合成封包测量。均使用独立 profile，`MES_TEST_CHROME`、`MES_TEST_OUTPUT` 控制浏览器与产物目录。容量结论及限制见 `docs/acceptance.md`。

第 7 组使用 `npm run test:phase7`（范围/网络/流/时钟/真实离线导出）与 `npm run test:platform`（BFCache、丢弃/replacement、真实开发者页面重载）。`npm run test:opening` 按 8 种打开方式各测量 3 次真实来源和首请求。`npm run test:permissions` 在独立预授权 profile 恢复原始 manifest 后，验证真实 API 撤权、子 frame 隔离、未授权导航返回和失败会话；不计原生弹窗验收。`npm run test:native` 是需原生界面操作的辅助脚本，步骤、确认格式和未覆盖组合见 [原生验收操作清单](docs/native-acceptance.md)；未完成右键菜单、快捷键及权限/F12 操作时不得算通过。结构化报告区分断言数、涉及 T 编号数与完整验收状态。

导出历史分别记录生成、下载和失败状态；生成中关闭控制页后显示“未确认完成”，可重试。取消或失败不会删除本地唯一证据，不同导出尝试不会覆盖彼此的结果。
