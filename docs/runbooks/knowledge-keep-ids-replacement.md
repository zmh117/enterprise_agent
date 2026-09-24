# keep_ids_v1 三库测试内容替换

这是用户明确授权的开发环境快照替换，不是通用增量同步或删除推断。数据采集调度保持关闭。代码从根目录的缺陷、工单、Story、子任务明细及配套字典/采集说明读取，不递归摄入 `验收/`。

## 内容与索引

- 缺陷 → `ones-defects-offline`；工单 → `ones-tickets-offline`；Story 与子任务 → `ones-stories-offline`。复用 `knowledge` 表，以 KB 成员、来源和文档类型隔离。
- ID 用于关联和权限核验，名字进入文本上下文。字段 ID、原始枚举值及名称映射保留在规范化属性中；未映射人员保留 ID，不伪造名字。
- 父子关系保存实际 `parent_uuid` 证据。正文缺失时使用标题块，标记 `title_only`；不补造正文。
- 评论本轮 `not_indexed`，附件/图片不下载，不执行 OCR。
- 新分块 profile 为 `ones-keep-ids-hybrid-chunks/v1`；旧 profile 不原地改变。每个 chunk 在同一 Qdrant collection 中保存 BGE-M3 `dense` 与原生 BM25 `bm25` 两个命名向量；payload 不保存正文。
- BM25 用 multilingual tokenizer，关闭词干和停用词，其他参数由 `domain/hybrid.py` 固定。入库/查询使用同一参数。Qdrant 镜像固定 v1.19.1。
- 检索采用等权 RRF（两路权重 1:1，k=2），每路最多 100 点，合并最多 200 点。不是把两路原始分数各乘 50%。两路重叠到达单路上限时仍标记可能截断，不默认为完整结果。
- 在线依旧执行应用内角色 KB 授权与用户 ONES 可读校验；候选最多核验 50 个文档，保留现有最长 120 秒总预算。任一路失败不静默退化。

## 维护顺序

必须先检查当前数据库 schema、非终态 Job、资源修订和磁盘容量。schema 144 与配套服务需经明确维护授权部署。不要在测试里使用业务 PostgreSQL DSN。不要删除 schema 或卷。

本机 Compose 按 [knowledge README](../../knowledge/README.md) 同时加载主栈、知识离线和在线 overlay，以及既有两个受管 env 文件；不能打印其内容。以下只展示容器内命令部分：

```sh
python -m app.cli.replace_ones_knowledge --mode preflight --input-dir /input
python -m app.cli.replace_ones_knowledge --mode stage --input-dir /input --resource-id <已有资源ID> --commit
python -m app.cli.replace_ones_knowledge --mode chunks --run-id <run-id> --commit
python -m app.cli.replace_ones_knowledge --mode benchmark --run-id <run-id>
python -m app.cli.replace_ones_knowledge --mode index --run-id <run-id> --capacity-path /qdrant_capacity --commit
```

`/input` 必须只读挂载，`/qdrant_capacity` 是同一 Qdrant 数据卷的只读挂载，仅用于读取剩余容量。CLI 默认期望缺陷/工单/Story 各 2000、子任务 6654；其他规模需显式传入四个计数。错误输出只含安全错误码，不能打印原始业务对象或完整异常。

候选阶段写入修订与索引，但不修改当前正文指针、收录成员或已发布版本。中断后使用同一 `run-id` 重放 index，验证已有向量点后复用；不要重新创建绑定或任意修改 checkpoint。容量不足保守暂停，不自动删除旧索引腾空间。

## 核验与切换

激活仅在已有 API 维护环境执行，复用受管存储凭据和真实管理员权限；离线 ops 不增加解密权限：

```sh
python -m app.cli.replace_ones_knowledge --mode activate --run-id <run-id> --actor-id <管理员用户ID> --commit
```

它只处理明确标记的三库测试替换，先逐点核验三套索引，再核对当前管理员权限、资源范围、草稿、发布修订、来源基线与候选成员。已发布连接必须指向同一物理 PostgreSQL（比较集群身份及数据库 OID），且其 Qdrant 端点能读到完整候选；不会因地址是别名就覆盖连接配置，更不会把外部库切回平台库。

数据库事务原子提交当前内容/成员、已有资源的新发布修订及运行水位。发布中途失败全部回滚；已经激活的同一运行重复执行不产生第二次发布。不自动创建/首次发布资源，不修改应用与角色授权，不覆盖管理员草稿。

旧测试内容仅从新知识库成员中移出，原始导出文件、旧修订和旧索引保留为历史，不能称为物理删除。旧发布摘要保留不改写；新发布使用按 KB 成员计算的 configuration_version 4。历史发布不代表可直接回滚当前内容，恢复需重新核验匹配的成员、修订和索引。

Knowledge MCP 的精确读取授权需含 `knowledge.document.document_kind`、`knowledge.retrieval_revision.configuration_version` 以及 `knowledge.vector_index` 的 `sync_run_id/source_id/unreferenced_at`。已有账号仅补精确列权限并执行 `assert_reader_role`，不重置口令、不授整表权限。

## 三路效果评测

```sh
python -m app.cli.replace_ones_knowledge --mode evaluate --run-id <run-id>
```

在同一已激活语料上，按稳定文档 ID 排序分别抽取每库前 10 个标题问题及前 10 个至少 80 字的正文片段问题，比较 BM25、dense、hybrid。输出自项命中率 @1/@5/@10、MRR@10、p50/p95 延迟和错误数，绝不输出问题、正文或命中原文；网络/索引错误使评测退出失败，不将部分结果当完整验收。

这属于已知项自查询，标签只包含自己，不能证明真实业务 Recall、语义改写能力或 1:1 权重最优。真实用户问题与人工相关项标签应另建受管评测集；本机无真实 ONES，离线效果和合成双重权限测试不能替代真实 ONES 授权验收。
