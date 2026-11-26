# 现场接入与浏览器支持清单

2026-11-16。本清单是后续接入输入，不将尚未接入真实 MES 或可选上传计为本地功能失败；未提供的值不以 fixture 默认值替代。

## 浏览器支持范围

- 本次可复核的运行范围是 macOS arm64、Chrome for Testing **157.0.8103.78**、独立 profile。生产 manifest 与测试复制件的权限模式分别记录；企业策略尚未验证。
- `minimum_chrome_version=125` 和构建 target `chrome125` 表示 **API/语法技术下限**，不等于 Chrome 125 兼容验收通过，更不表示所有 125+ 版本均获支持。125 是 flat debugger child session 的起点，见 [Chrome 官方 debugger 说明](https://developer.chrome.com/docs/extensions/reference/api/debugger#attach-to-related-targets)。目前交付的已验证支持声明只覆盖上面的 157 构建及实际通过的场景。
- 本轮从 [Google 官方 Chrome for Testing 清单](https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json) 取得 125.0.6422.141 mac-arm64。旧 headless 未出现扩展 service worker；new headless 在测试准备阶段读取 debugger API 失败；可见模式遇到 service worker 重启。三次均未完成有效业务断言，不能归结为产品已兼容，也不能仅据工具启动失败判定产品 API 不兼容。历史记录见 `output/playwright/phase7-browser-support.json`。本次按 manifest 识别 worker 后，新 headless 实际到达采集阶段：页面/语义就绪，网络/错误随即收到 `debugger_detached:canceled_by_user` 并降级；未执行用户取消操作，事件原因仍待独立验证。P0 在四通道就绪断言前超时，日志与状态保留于 `output/playwright/phase8-chrome125-diagnostic/`；这不是 Chrome 125 兼容通过，也不是原生取消调试验收。
- 若现场要求 125 或另一企业稳定版本，应在该版本的普通独立 profile 实际加载生产 dist，先验证权限、四通道、同源/OOPIF/worker，再运行范围、恢复、停止和离线导出矩阵；保留浏览器版本、策略和构建 hash。未完成前保留待验收。

## 必填现场输入

| 输入 | 目前状态 / 对应配置 | 现场验证步骤 |
| --- | --- | --- |
| MES 环境标识及页面域名 | 待提供；`environmentId`、`pageOrigins` 必须精确到 origin | 按实际根页面和 iframe 分别核对授权，未选页无证据 |
| API 域名、路径及请求类型 | 待提供；`apiRules`、`requestTypes` | 正常请求、重定向、跨域 frame、专属 worker 分别采样；禁止扩大到任意站点 |
| 业务成功码 | 待提供；`businessRules` 的 origin/pathPrefix/codePath/successValues | 同时验证成功、业务失败、HTTP 失败；未配置时保持 unknown |
| 输入字段与查询参数 | 默认 `allowedInputNames=["*"]`、`allowedQueryKeys=["*"]` | 按用户决定保留普通原值；现场核对业务 ID、版本和精度 |
| 登录密码识别 | type=password、密码 autocomplete、password/passwd/pwd/pass 等字段及 Basic 密码 | 核对真实登录字段与显示密码操作；自定义非标准密码协议需要明确字段适配 |
| 额外敏感区域 | 默认 `sensitiveSelectors=[]`、`maskAllText=false` | 仅用户另行配置时启用，检查桥接消息、IndexedDB 和 ZIP |
| 前后端构建、服务实例、日志 ID | 待提供；`correlationSources` | 指定已发生响应头、JSON Pointer 或页面 meta；日志按真实 requestId/traceId 匹配，不重放请求补 ID |
| 构建到源码映射 | 待提供；`sourceMappings` 与可信部署记录 | 对照现场构建和源码快照 hash/提交；人工配置只标 configured_unverified，缺失或冲突仍 unresolved |
| 企业浏览器/扩展策略 | 待提供；版本、安装方式、host policy、debugger 限制 | 用未经修改的 manifest 验证混合授权、撤回、F12/取消调试；不绕过企业策略 |
| 保存预算、时长与留存期限 | 待提供；budgets 与现场清理流程 | 用实际页面负载测量；本地手动删除和下载副本分开管理，当前没有自动到期清理 |
| 证据交付/访问负责人 | 待提供；本地 ZIP 交付方式和访问范围 | 验证接收方能校验、按需读取，定义删除时间；不将证据文本作为 Agent 指令 |
| 可选上传服务 | 未接入，非本地闭环前置项 | 若需要上传，另行明确接口、认证、权限、失败重试和留存约束后验收 |

现场验收应至少覆盖一个正常保存、一个实际业务失败、一个导航/关闭中断及一个离线导出，绑定配置、版本、日志和源码。fixture 的 `OK`、版本 1/2、域名和 requestId 格式只供本地测试，不能直接作为生产协议。

## 从页面 URL 绑定车间

连接系统并在「Agent 对话」选择业务应用。在「站点设置 → 页面车间」选择已经打开的页面，再选择环境、基地和车间，点击「允许页面并绑定车间」。同域的页面可按路径或 hash 路由区分。仅在车间由查询参数区分时填写业务定位键，预览中只会显示选定的键和值。浮窗显示命中的范围。授权页面不会启动录制。旧站点的离线环境不能自动推断车间，需要补选；撤销或改绑只影响后续使用。

在「数据采集」选择「持续采集」并勾选标签。刷新控制页可以查看正在采集的标签；同一 URL 的两个标签各有独立的实例。持续模式在本地保存页面结构和操作类型，移除页面文字、属性和输入值。浏览器只在新文档收到结构基线后才接受操作。

在同一标签用单页路由从车间 A 切到 B 时，该页会显示“页面采集已暂停”。即使再切回 A，仍须刷新或重新打开页面。其他已选标签继续采集。关闭后重新打开会得到新的标签实例，可在持续采集面板点击「刷新标签」并选择「加入持续采集」。

持续录制达到本场本地空间上限时，插件只用已经从 Loki 逐片读回、核对摘要的材料腾出空间。待传和仅获转发回执的内容继续保留。如果仍然无法写入，控制页会显示采集缺口。
