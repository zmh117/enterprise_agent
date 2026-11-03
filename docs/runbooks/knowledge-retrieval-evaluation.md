# 知识检索本地评测

本入口在同一候选快照上比较原排序和固定本地 Cross-Encoder 重排，记录实际 `dense` / `hybrid_rrf` 模式。它复用在线的 200 点召回、当前块校验、文档去重和前 50 篇候选池，不实现用户授权、真实 ONES 回源或聊天模型端到端验收，不写数据或重建索引。首批业务效果建议准备约 50 条人工问法，不能用原文自查询代替。

## 标注集和受限目录

格式见[纯合成样例](../../knowledge/evaluation/synthetic.dataset.json)；严格合同由[评测集校验器](../../backend/app/modules/knowledge/domain/evaluation.py)的 `DATASET_SCHEMA` 定义。样例中的 source/工作项身份都是虚构的，只能用于格式演示，不能对正式索引直接运行。

- 每个文件固定一个知识库 code、一个明确离线 source ID 和一个 dataset version。多知识库/来源分别评测，禁止按显示名称猜来源。
- `basis=human` 必须由人工标注并复核，`annotation.origin=human_reviewed`、`reviewed=true`；这只是标注人声明，不是系统自动证明质量达标。
- 合成集使用 `synthetic/synthetic_fixture`；原文自查询使用 `self_query/pipeline_probe`，案例分类必须为 `pipeline_probe`，不能混入人工集。
- 每条案例必须有唯一 `query_id`、1–2000 字符 `query`、明确 `category`、`no_answer` 和 `relevant`。相关项支持 `document` 内部 UUID 或 `work_item` 来源工作项 ID；二者解析到同一文档时只算一个相关文档。
- 无答案必须显式写 `no_answer=true` 和空相关数组；遗漏标签与无答案不同，会拒绝。标签不穷尽时设置 `labels_complete=false`，报告明确为标注集内召回。
- 单文件最多 2 MiB、500 条问题、每问题 100 个相关引用；重复 JSON key、重复 query_id/标签、未知字段、错误类型和模型生成标签来源均拒绝。

真实问题/标签只放本机 `.local/knowledge-evaluation/`（已加入 Git ignore），目录权限 `0700`，文件权限 `0600`。CLI 要求文件及父目录对组/其他用户不可读写，不接受符号链接、硬链接、管道或设备。不要在聊天、日志、命令参数或仓库中粘贴真实问题/标签。文件应由有权标注者在受限目录编辑，不使用自动生成的“正确答案”。不要把输出重定向到真实输入文件。

```sh
# 仅校验已准备的受限文件；不加载数据库配置，不调用任何服务。
.venv/bin/python -m app.cli.evaluate_knowledge \
  --dataset .local/knowledge-evaluation/dataset.json --validate-only
```

真实运行需要当前 schema 的 `knowledge-ops` 镜像和已经就绪的本地 Embedding/Qdrant/Reranker。只读挂载受限目录到 `/evaluation`，不把文件复制进镜像：

```sh
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/mcp.compose.yml --profile knowledge \
  run --rm --no-deps -T \
  -v "$PWD/.local/knowledge-evaluation:/evaluation:ro" knowledge-ops \
  python -m app.cli.evaluate_knowledge \
  --dataset /evaluation/dataset.json --index-code ones-defects-bge-m3-v1
```

路径中不携带查询文本。不要打印完整 Compose 配置、数据库连接信息或原始异常。Docker 内外 UID/权限映射导致不可读时应修正受限挂载方式，不把目录或文件改成全员可读。

## 计算与报告

开始前验证 READY、知识库、明确 source、语料/profile/hash；全部标签必须属于该索引当前有效且已收录的文档，失效/缺失标签在首个模型请求前拒绝。运行结束再次核对语料、索引和代码摘要，有变化则不交付可比较的指标。

- 一次召回最多 200 点，按原检索分聚合并保留前 50 篇；基线和重排从同一池各取前 20。不得分别调用召回后宣称同候选对照。
- 同时报告去重后完整候选池覆盖率和前 50 篇覆盖率，区分未召回与排序靠后。覆盖率以有答案问题的标注相关集合为分母。
- `baseline` / `reranked` 各含 Recall@5/10/20、MRR@10、Hit@3 及分类指标。Recall 按问题计算再平均；MRR 是首个相关文档倒数排名的均值；未命中为零。
- 有答案故障计零且不从分母移除。重排故障保留同快照的基线指标、重排计零；召回故障两者均计零。线上检索发生重排故障会明确失败，不退回原排序。
- 无答案单列总数、完成数、`candidate_returns` 和 `candidate_return_rate`；完成数为零时 rate 为 null。它只表示返回了候选，不表示 Agent 错误作答。回答误报必须单独通过真实 Agent 核实。
- 报告 `encoding/retrieval/reranking/total` 耗时、截断比例、`partial_rate`、`bounded_rate`、失败类别。p95 表示约 95% 请求不超过该耗时，使用 nearest-rank；少量样本的 p95 仅供观察。
- 报告只含汇总、索引/KB/source 身份和数据集/代码/候选快照/语料/embedding/chunk/ranking profile 摘要；不输出问题、query_id、标签、命中清单、文本或原始异常。
- 完成时重新校验候选 revision/块 hash、索引、来源、代码和 ranking profile；包括增量索引中保持 index ID 不变但内容变化的情况。变化使比较无效。
- `end_to_end_latency=null`、`authorization_verified=false`。离线耗时不包括 ONES 可读性、详情或 Agent 模型响应；不能替代在线总检索 p95 或 Agent 端到端验收。

有任一调用故障时 CLI 输出脱敏汇总但退出码为 1；输入、语料或版本不合法时只输出固定失败码，没有部分指标。真实人工集也始终 `business_acceptance=false`：取得基线后仍需用户确认质量/时延门槛和双权限端到端复测。纯指标函数支持按当前授权观察得到的可见相关集合计算，但本离线 CLI 不接受文件自报权限，也不宣称已执行权限校验。


## 重排服务准备、发布和回退

固定模型采用 `BAAI/bge-reranker-v2-m3`，revision/文件摘要见 `backend/app/modules/knowledge/reranker_model.json`。文档端最多 1024 token、配对上限 4096 token，保留完整 query，候选两块平分文档额度并受配对剩余空间限制；超长 query 无有效文档空间时明确返回输入上限错误。微批按长度分组，最多 8 对/8192 个 padding 后 token，再恢复原文档顺序。固定 CPU 推理依赖复用现有 amd64/arm64 embedding runtime 锁，ranking profile 同时包含模型、依赖摘要和窗口/微批/排序边界。新服务不需要改变向量索引、分块或知识资源身份。

```sh
# 显式下载和核对公开模型；运行服务随后只读、离线加载。
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge-prepare \
  run --rm --no-deps --build knowledge-reranker-prepare
# 在确定的部署窗口启动独立内部服务；不发布宿主机端口。
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/mcp.compose.yml --profile knowledge \
  up -d --build knowledge-reranker
```

用户允许增加 CPU 以保留大模型和长文本，当前配置为 8 vCPU / 3 GiB，内存与 memory-swap 上限相同；线程为 8，单实例 1 执行 + 3 等待。知识目录和检索总预算为 360 秒，并取 Job 剩余时间与上游截止的较小值；排队、输入准备与微批推理共享调用方原截止时间；执行取消须等计算退出才释放槽位。`/health` 仅代表进程，`/ready` 代表固定模型加载完成，`/profile` 必须与本地 `fingerprint(profile())` 一致。健康不代表效果或容量通过。本机 8 核测试的 50 篇满长窗口合成输入曾触发原 120 秒截止，改为 180 秒后同一重排样例在 132.37 秒完成；4 核同样例在 180 秒下超时，改为 240 秒后用 230.02 秒完成，距上限约剩 10 秒。这不承诺所有合法输入或四请求的完整检索容量，详见本次 change 的 evidence.md。测试前另行确定业务 p95 门槛；不得把新的 360 秒硬截止当目标 SLA。

超过 300 秒的在途请求通过固定内部入口续期 Knowledge Principal，单张 TTL 仍不超过 300 秒。到期前 60 秒续期，每次最多 5 秒；平台与 MCP 两端复核身份、Job 和权限，失败取消检索，不重新推理。新版固定服务 scope 增加 `internal:knowledge:principal:refresh`，需协调升级签发/验证端并重新获取服务身份。续期仅在当前调用内有效，不为后续工具调用或重试保留票据。若 Job 剩余预算不足 360 秒，仍按较短预算结束；不能通过续期延长 Job。

`knowledge_search` v2 将 `score` 改为 `retrieval_score`，新增连续 `rank`、实际检索模式及 ranking profile；不返回重排 logit。input schema 的固定 `$comment=knowledge-search-contract/v2` 进入既有 schema hash，旧 Publication/Job 会继续因合同不匹配被拒绝。协调发布步骤：

1. 截止上限已由 240 秒调整为 360 秒，需协调重建 Knowledge MCP、在线 Embedding、Reranker 及配套 API/ONES MCP；只更新模型服务无法解除外层旧截止。保存现有镜像版本与已发布合同摘要，准备模型并验证固定 profile，在隔离环境完成质量及资源测试。
2. 在发布窗口更新 MCP/API/Worker/Runtime 中使用统一工具合同的组件；确认实际 MCP tools/list 与 Runtime 冻结输入 schema 均保留 v2 注解。
3. 通过既有应用/Agent 发布流程产生新 Publication，使用新 Job；不修改历史快照。复测 ONES 可读性、撤权、最新详情和统一 Agent 核实规则。
4. 回退须协调恢复 API/MCP 的服务身份 scope、代码镜像与对应工具合同，并重新发布产生匹配的 Publication/Job；不得只停掉 reranker 或在运行中静默改用旧排序。独立模型卷可保留，既有索引无需回滚。

尚无人工作业集时，可在授权本地数据上做有界候选/性能诊断，并明确标记标签来源。原文标题自查询或自动生成问法只能作流程检查。建议从约 50 条独立问题建立人工调参集与按问题/事项隔离的冻结验收集，再验证 MRR@10 提高、Recall@20 不下降；已知漏排问题单列前 3 命中，候选不存在时先记录召回/数据缺口。
