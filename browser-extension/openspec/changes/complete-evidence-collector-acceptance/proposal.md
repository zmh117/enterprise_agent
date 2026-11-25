# Proposal

## Why

当前扩展已经具备真实浏览器采集、本地保存和 ZIP 导出的主流程，但现有 48 项浏览器断言并不等于开发规格 T01–T50 全部验收完成；代码中还存在证据归属、敏感区域处理、通道状态及问题包校验方面的缺口。需要先完成高风险行为修正，再补齐真实浏览器与故障场景证据，形成可审查的 A0–A3 交付结论。

依据为项目根目录的 `MES_Browser_Evidence_Collector_Development_Spec.md` v1.0.0、当前源码、`docs/acceptance.md` 和现存测试产物；逐项核对见 [现状审计与 T01–T50 对照](evidence-audit.md)。本提案只安排后续工作，不把代码路径存在、历史检查通过或文档生成完成等同于实现验收完成。

## What Changes

- **P0：修正敏感区域语义采集边界。** `targetOf()` 对 `data-*` 属性仅作关键词脱敏，尚未统一应用敏感区域策略；同时补足无效选择器、未标记敏感值和业务字段允许规则的反例验证。
- **P0：补齐可验证的文档与基线关联。** 分开维护 Chrome frame/document、CDP frame/执行上下文和 rrweb 流/节点；已知顶层与同源关系准确填写，无法确认的跨源节点保留原因。建立子文档与父流 iframe attach 基线的引用，避免永久停留在含糊的 `pending_baseline`。
- **P0：收敛通道就绪与部分失败行为。** 修正单通道启用失败未结束 PENDING、控制页以“任一通道可用”掩盖降级、权限请求整体失败阻断已有有效根等路径；维持严格截止和单通道失效隔离。
- **P1：完善语义、资源和停止行为。** 明确动作前后状态的观察依据、弹框开关及截断范围；将正文并发与队列按标签统一约束；为已接受数据的慢写入、失败重试和停止超时提供真实状态。
- **P1：完善问题包消费契约。** 对齐 JSON Schema、运行时验证及引用闭包，补充前后端构建/源码映射的配置入口与证据来源、混合部署记录、错误观测归组和有界摘要。
- **BREAKING：收紧问题包与证据身份校验。** 不符合新约束的旧开发样例重新采集；确需不兼容字段或存储调整时显式升版并重建开发数据，不引入历史数据迁移层。
- **P1：补齐验收证据。** 将 T01–T50 对照到具体断言及产物，补齐 BFCache、正式 replacement、右键打开、F12/取消调试、权限混合失败、真实离线导出、扩展重载、共享/专属 worker、故障注入和容量测量。条件无法复现的项目保持待验收，不以模拟事件冒充真实浏览器验收。
- **交付边界：** 保留截图停用及已知平台缺口，按原规格允许的降级策略说明适用范围。真实 MES 配置与可选上传分别列为现场接入项和可选项，不阻塞本地模拟 A0–A3，也不宣称已接入生产。

## Capabilities

本变更的真实录制补充（2026-11-17）见任务第 9 组：修正 text/plain JSON POST、压缩响应正文限额/失败原因、导航 frame 授权时序与 ExtraInfo 无事件状态。保持冻结策略、严格截止和不重发现场请求的边界，历史录制不回填。

用户随后明确选择“全部原样保存，仅保护登录密码”，本变更以该决定更新默认隐私策略：移除通用凭据/令牌与文本掩码，保留密码输入和明确密码字段保护；普通 URL、头、输入与正文值保留。此要求替代原提案中“所有认证凭据不得持久化”的默认范围，历史 P0 检查只代表当时策略。额外敏感选择器仍可由用户手动配置，默认关闭。

### New Capabilities

当前 `openspec/specs/` 无主规格。以下为首次纳入 OpenSpec 的能力边界，包含已有行为的必要约束与待补足要求，并非声称这些产品能力全部从零实现。

- `capture-session-health`：采集通道状态、部分启动、恢复与严格停止、每标签资源约束。
- `document-evidence-context`：文档/流/节点归属、子文档基线关联、语义状态及源时钟解释。
- `evidence-redaction`：按敏感区域和允许规则处理所有页面语义字段，保证脱敏失败时不保存原文。
- `problem-evidence-contract`：问题包结构与引用校验、版本和日志关联、错误归组、摘要及按需消费。

### Modified Capabilities

无现存 OpenSpec 主规格可修改。此次不提前同步或归档尚未实现的要求。

## Impact

- 主要代码范围：`extension/background/session/`、`extension/background/cdp/`、`extension/page/recorder.ts`、`extension/content/bootstrap.ts`、`extension/storage/database.ts`、`extension/export/package.ts`、`extension/ui/`、`shared/`。
- 验证和交付范围：`fixtures/`、`tests/`、问题包校验脚本、`docs/acceptance.md`、`docs/protocol.md`、`docs/agent-consumption.md`、README 与重新生成的样例包。新增测试依靠已有工具，按场景拆分现有浏览器脚本，不建设通用测试平台。
- 继续使用现有 TypeScript、rrweb、IndexedDB、fflate 与 Manifest V3 架构；不引入协调后端、播放器、跨 profile 采集、请求重发或源码/日志新平台。
- 契约收敛拟增加构建期 JSON Schema 校验代码生成依赖，扩展只运行静态校验函数，不动态编译或加载远程代码。
- 不预设生产域名、成功码、版本接口、企业最低浏览器版本及保留期限；缺少现场信息时保留 unknown/unresolved，并在接入清单中说明。
