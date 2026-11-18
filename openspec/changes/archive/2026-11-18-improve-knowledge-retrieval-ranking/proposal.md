## Why

当前知识检索按候选块分数聚合文档后直接截取结果，缺少对完整问题与文档的联合相关性判断；工具未说明分数语义，Agent 可能用未经标定的阈值跳过正确候选，并将相似机制解释为已确认根因。本次用户反馈说明需要同时改进候选排序、查询与核实规则，并用人工标注问题验证实际收益。

## What Changes

- 按用户后续确认，将知识目录与检索的端到端硬预算由 120 秒调整为 360 秒；仍取当前 Job 剩余时间与上游截止的较小值，各阶段不得重置预算。

- 在现有 dense / BM25 + RRF 召回后，增加最多 50 篇文档的本地 Cross-Encoder 重排，复用当前已校验的分块文本；保持最多 200 个候选点、当前 ONES 可读性检查和引用式返回。
- 新增固定模型的本地重排服务，首个评测模型为 `BAAI/bge-reranker-v2-m3`；锁定模型与运行依赖，限制请求、排队、推理和总预算，明确失败语义。
- **BREAKING**：知识检索输出增加最终 `rank` 与检索/排序方式，文档及证据的含糊 `score` 改为 `retrieval_score`，重排数值只用于内部排序和受限评测。所有排序分均不得被解释为相关概率或用于 Agent 自设过滤阈值；不保留双字段兼容。
- 固定 Agent 使用规则：原话优先、证据不足时最多补一次保真同义查询、按来源工作项去重核实，并区分症状符合、机制假设与现场根因。未核实和有界检索不得被表达为全库不存在。
- 扩展现有评测入口，对相同候选同时比较原排序与重排，报告候选覆盖、前列召回、排序质量、失败和阶段耗时；修正实际运行混合检索却固定标记 `offline_dense` 的报告问题。
- 以人工复核的独立问法、近似干扰项、无答案问题和已知漏排案例建立发布门槛。原始业务问答、正文及凭据不写入本 change、仓库夹具或普通日志。

## Capabilities

### New Capabilities

无新增 canonical 领域；新增要求归入以下既有领域。

### Modified Capabilities

- `identity-access`：在不改变 Business Principal 300 秒 TTL 的前提下，为知识工具在途请求补齐双身份、同绑定续期。

- `builtin-tool-resource`：修改知识检索的返回合同，增加有界文档重排、排序分使用、查询保真和证据核实要求，保持当前授权、版本检查与正文回源边界。
- `platform-operations`：增加固定本地重排服务的模型准备、资源与截止时间管理，以及可复现检索对照评测和分阶段发布验收要求。

## Impact

- 主要代码：`backend/app/modules/knowledge/application/{search,candidates,vector_service,evaluation}.py`、知识 ports / 基础设施装配、`backend/app/shared/knowledge_tool_contracts.py`、Runtime 的既有知识使用指令注入和 MCP 合同测试。
- 新增组件：`services/knowledge_reranker/`、固定重排 profile / 模型清单 / 架构依赖锁；接入现有 `knowledge/compose.yml` 与 `knowledge/mcp.compose.yml`，更新模型准备和运行手册。
- 评测与验证：扩展 `evaluate_knowledge`、指标合同、代码/profile 摘要和相关合成回归；真实模型效果、目标机器时延及真实 ONES 端到端核实独立验收。
- 预期不新增数据库业务表，不修改分块或向量 profile，不重建 collection，不改变 ONES 采集和同步范围。只改变查询时派生排序；增加 CPU / 内存 / 模型存储开销。
- 输出变更需要协调 MCP、Runtime 工具合同及现有发布/Job 快照策略，旧快照不得被静默改写。具体发布步骤在设计中说明。
- **Confirmed-current**：上述现有检索流程、分数合同和评测标记问题已由源码核对。**Documented-intent**：重排、效果门槛和服务部署均为本提案目标；未证明生产首轮结果或调优后的真实收益。
