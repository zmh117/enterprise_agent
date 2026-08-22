## Context

当前实现同时存在 `text-v1` / `text-v2`、三个 Docling Profile、Job File Manifest v1-v5 和 Runtime protocol 1.0-1.3。历史合同已经进入注册表、数据库约束、Publication 快照、Worker 投影、Runtime 解析器、管理端选项和测试夹具，导致普通文字 Job 也可能因为旧文件合同投影失败。现有数据均属于开放测试数据，用户明确允许删除旧文件数据，并明确要求系统只保留当前最佳规则，不提供旧规则兼容或运行时切换。

本变更跨 Business Application、Channel/Job 创建、File Service、File Worker、File Processing Worker、Agent Worker、Python Runtime、管理端、数据库和对象存储。File Service 继续是唯一对象存储边界；文档原件、不可变版本、Representation、工作集和 Delivery 的安全边界不变。

## Goals / Non-Goals

**Goals:**

- 直接文本固定为 `text-v2`，TXT、Markdown 可读写，LOG 只读；Publication、Job 和 Runtime 不再保存或分支选择文本策略。
- 文档处理配置只允许关闭 `NONE` 或启用 `docling-layout-ocr-v2`；彻底删除 `docling-text-v1` 与 `docling-layout-ocr-v1`。
- Job File Manifest 只生成、持久化、传输和读取 schema v5；Python Runtime 只接受 protocol 1.3。
- 删除旧进程内 Office 提取链和重复文件身份影子字段，所有入站附件先进入任务工作区，再按唯一规则处理。
- 提供有门禁的一次性开放测试文件域重置，并在重置后收缩数据库约束、代码和测试矩阵。

**Non-Goals:**

- 不迁移、回填、读取或展示旧文件 Manifest、旧 Runtime 请求、旧文档 Representation 或旧 Profile 结果。
- 不提供按租户、Application、Publication 或 Job 切换文本规则的能力。
- 不把 Office/PDF/图片原件直接交给模型，也不恢复旧 `python-docx`、`openpyxl`、`python-pptx` 提取器。
- 不删除 `NONE`；它是关闭文档处理的当前策略，不是兼容 Profile。
- 不改变 File Service 的对象存储唯一入口、当前 RBAC、不可变版本、工作集、Sandbox v2 和 Delivery 边界。

## Decisions

### 1. 文本策略成为代码常量，不再成为 Publication 配置

系统以单一 `text-v2` 规则校验、物化、写入和提交直接文本。删除 Revision、Publication、Job 请求、API 和管理端中的文件格式策略选择及其 hash；需要审计当前合同的地方记录 Manifest schema v5 和 Runtime protocol 1.3，而不是复制一个永远不会变化的策略字段。

选择该方案是因为运行期间不会切换文件规则。保留单选下拉框、数据库枚举或“旧值解释为新值”都会继续制造虚假可配置性和兼容分支。

### 2. 文档处理保留一个开关和一个实现

Business Application 仍可选择 `NONE` 或 `docling-layout-ocr-v2`，因为“是否允许 Office/PDF/图片处理”属于应用能力边界。`docling-layout-ocr-v2` 的 options 和 hash 改为独立常量，不能从 v1 定义派生。注册表、API、前端和 Worker 不得认识另外两个旧 code。

不把所有应用强制启用 Docling，因为 `NONE` 仍用于显式禁止高成本或不需要的文档处理；这与旧版本兼容无关。

### 3. Manifest v5 在 Agent Worker 与 Runtime 间原样传递

Job 创建只写 schema v5，hash 只使用 v5 canonical payload。Agent Worker 不再把 v5 投影为 v4；Python Runtime 的 protocol 1.3 request schema 直接引用 Manifest v5。File MCP 列表、精确选择和物化都从同一冻结 Catalog Revision/Working Set 解析。

删除 v1-v4 parser、hasher、projector 和 fixture；遇到任何非 v5 持久化行或请求直接返回稳定合同错误，不执行模型。该失败关闭只用于发现部署不一致，不构成旧协议兼容。

### 4. Runtime 只保留 `python-v1` protocol 1.3

删除 `contracts/agent-runtime/v1`、`v1.1`、`v1.2` 及对应生成代码、版本协商、健康声明和恢复路由。Worker 只构造 1.3，Runtime 只校验 1.3；普通无文件 Job 也使用同一请求结构，并携带合法的空 v5 文件上下文或明确的无工作区状态。

未来升级仍必须发布新的显式变更，但本阶段不维护 1.3 之前的在线双读或双写。

### 5. 所有附件统一进入 File Service

删除 `attachment_content` 及入站服务中的 DOCX/XLSX/PPTX/Markdown 进程内提取。`message_attachment` 只保存渠道附件事实，canonical 文件绑定由独立 binding 表表达；模型上下文不再读取历史提取正文。TXT/LOG/Markdown 由 File Service 按固定文本规则形成可读版本，Office/PDF/图片只由 `docling-layout-ocr-v2` 形成 Markdown/JSON Representation。

这消除了同一附件同时经过旧提取器和 Docling 的双事实源，也使“附件导入成功但 Manifest 为空”只能在当前工作区/工作集链路内诊断。

### 6. 开放测试数据使用显式破坏性重置，不在运行请求中兼容

提供仓库内维护命令，必须携带精确确认参数并依次完成：只读预检；拒绝非终态 processing run、Job、Delivery、Outbox 或相关队列积压；通过 File Service 对象存储适配器删除受管文件对象；在事务内删除文件 Representation、processing、工作集、Catalog、Manifest、附件绑定、文件版本/逻辑文件/工作区和与其强关联的终态测试运行事实；最后验证数据库与对象存储均无遗留。

数据库 migration 在重置未完成、仍存在旧 Manifest/Profile/协议引用时失败关闭，然后删除旧表、旧列和宽松约束并安装唯一当前约束。migration 本身不直接访问 MinIO，也不把旧行更新成新合同。

### 7. 删除代码前先切断生产依赖

`python-docx`、`openpyxl` 和 `python-pptx` 从生产依赖删除。若测试仍需生成合成 Office fixture，依赖只能保留在开发依赖组；生产模块不得 import。删除旧合同目录、旧 registry 项和旧数据库字段后，以仓库搜索门禁防止旧标识重新出现，迁移文件和本变更文档中的历史说明除外。

## Risks / Trade-offs

- [破坏性重置不可在线回滚] → 执行前要求停止入站、排空相关队列并创建操作者选择的数据库/对象存储快照；回滚只能恢复整套快照和前一代码版本，不提供在线旧合同读取。
- [删除历史 Publication/Job 引用可能触发外键] → 预检输出精确引用计数，重置按外键拓扑删除终态测试事实；任一活动部署或非终态引用都会阻止迁移。
- [普通文字 Job 被强制文件合同影响] → protocol 1.3 明确定义空 v5 文件上下文，增加无附件文字 Job 合同测试。
- [v2 当前实现从 v1 常量派生] → 先把 v2 完整 options 固化为独立常量并验证 hash，再删除 v1，防止删除顺序改变 v2 行为。
- [对象存储与数据库清理不一致] → 对象删除先产生有界结果，数据库删除后执行空域核验；失败时停止后续 migration，不伪造完成状态。
- [并行工作树已有测试治理修改] → 实施只修改本变更明确文件，遇到重叠文件先合并现有改动，不回退用户或 Cursor 的未提交工作。

## Migration Plan

1. 完成当前代码、数据库、队列和对象存储只读预检，确认无非终态文件处理/Job/Delivery 和活动旧 Profile 部署。
2. 停止 Channel ingress、Agent Worker、File Worker、File Processing Worker 和 Delivery Dispatcher；排空或显式处理 dead-letter。
3. 按显式确认运行开放测试文件域重置；验证受管对象、文件域表、Manifest/Working Set 和旧附件提取表数据达到预期空状态。
4. 部署前向 migration：删除旧测试引用与旧列/表，收紧为 text-v2、Profile `NONE|docling-layout-ocr-v2`、Manifest v5、Runtime 1.3 的单一合同。
5. 部署 File Service、File/Processing Worker、API、Agent Worker、Python Runtime 和管理端；不得保留旧容器或旧合同回退。
6. 运行 schema contract、后端/前端回归、Compose readiness、无附件文字 Job、直接文本、DOCX/PPTX/XLSX/PDF/图片、工作集选择、Sandbox 物化及 Delivery 的新鲜 E2E。
7. 只有 E2E 和旧标识搜索门禁通过后恢复入口流量。

回滚只允许在恢复流量前恢复成套快照与上一镜像；恢复流量后不支持旧数据或旧合同回滚。

## Open Questions

无。用户已经确认唯一当前规则、旧 Profile 删除和开放测试文件数据可全部清空。
