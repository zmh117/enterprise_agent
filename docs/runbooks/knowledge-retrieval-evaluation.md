# 知识检索本地评测

本入口只运行离线 dense 检索基线，不实现用户授权、真实 ONES 回源或聊天模型端到端验收。它复用现有 `VectorService.query`，不导入数据、不迁移数据库、不创建索引或发布资源。首批业务效果建议准备约 50 条人工问法，不能用原文自查询代替。

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

真实运行需要当前 schema 的 `knowledge-ops` 镜像和已经就绪的本地 Embedding/Qdrant。只读挂载受限目录到 `/evaluation`，不把文件复制进镜像：

```sh
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge \
  run --rm --no-deps -T \
  -v "$PWD/.local/knowledge-evaluation:/evaluation:ro" knowledge-ops \
  python -m app.cli.evaluate_knowledge \
  --dataset /evaluation/dataset.json --index-code ones-defects-bge-m3-v1
```

路径中不携带查询文本。不要打印完整 Compose 配置、数据库连接信息或原始异常。Docker 内外 UID/权限映射导致不可读时应修正受限挂载方式，不把目录或文件改成全员可读。

## 计算与报告

开始前验证 READY、知识库、明确 source、语料/profile/hash；全部标签必须属于该索引当前有效且已收录的文档，失效/缺失标签在首个模型请求前拒绝。运行结束再次核对语料、索引和代码摘要，有变化则不交付可比较的指标。

- top_k 固定 10，复用既有至多 200 候选点及文档去重规则，不增加相似度阈值或另一套召回实现。
- Recall@10 为每条有答案问题的已命中相关文档数/标注相关文档总数，再取问题均值；MRR@10 为首个相关文档倒数排名的均值，未命中为零。重复块不占额外文档排名。
- 有答案问题发生检索故障时计零并单独记录失败，不从分母移除。无答案故障不算“正确拒答”，报告其总数、完成数及完成样本误报率；完成数为零时误报率为 null。
- 无答案误报指返回任意文档。当前 dense 检索没有拒答阈值，可能有较高误报率；不能把存在分数当相关性保证。
- 报告只含分类计数、指标、失败枚举、索引/KB/source 身份、数据集/版本/代码/语料/profile hash、运行环境与参数；不输出问题、query_id、标签、命中明细或底层错误。
- 延迟包含本地 Embedding、Qdrant 和来源核对，单位毫秒，p50/p95 使用 nearest-rank。当前无 ONES 权限/详情调用，`end_to_end_latency=null`、`authorization_verified=false`；不得把它作为 Agent 端到端延迟。
- `partial_rate`、`bounded_rate` 以全部问题数为分母，故障另列；`unmatched_answerable_cases` 仅统计调用成功但零相关命中的问题。

有任一调用故障时 CLI 输出脱敏汇总但退出码为 1；输入、语料或版本不合法时只输出固定失败码，没有部分指标。真实人工集也始终 `business_acceptance=false`：取得基线后仍需用户确认质量/时延门槛和双权限端到端复测。纯指标函数支持按当前授权观察得到的可见相关集合计算，但本离线 CLI 不接受文件自报权限，也不宣称已执行权限校验。
