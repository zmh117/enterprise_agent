# 实现与运行验收（2026-09-17；持续更新）

## 当前边界

用户同意继续后，采用官方固定 PyTorch bin 的受限加载，不转换、不用 ONNX。已完成代码、ARM64 CPU 镜像、全部官方文件校验、实际离线推理、全量 token 预检和 100 块真实基准。尚未执行正式迁移和全量索引；因预计需约 2.5 小时，已询问用户是否现在后台执行并继续验收。本文件不能被解释为全部任务完成。

未改变 `storage_only` / `offline_unverified`，未启用 Web、MCP、用户授权、OCR、采集或外部推理。

## Compose 可选部署拆分验收（2026-09-17）

用户确认后完成任务 1.4：四个知识服务、知识专用网络和两个卷移入 `knowledge/compose.yml`；扩展仅追加 PostgreSQL 的知识网络，根 Compose 不再包含知识定义。新增 `knowledge/README.md` 并更新运行手册中的全部知识启动命令。保留主项目、内部地址、数据卷及安全隔离；数据库连接从既有 `DATABASE_DSN` 提供，缺失/空值失败，不复制凭据。当前本机解析后的连接与拆分前一致。

- 新增 10 条部署配置用例，登记 contract tier；实际调用 Docker Compose CLI 解析合成配置，禁用真实 `.env`/环境凭据继承，不依赖 Docker daemon 或业务数据。
- 验证仅主文件（默认/全部 profiles）均不含知识服务、专用卷或网络，不要求知识 DATABASE_DSN；扩展分别验证未启用 profile、knowledge、knowledge-prepare 和全部 profiles。覆盖构建相对路径、发布参数一致性、数据库网络合并、主服务未变、缺失/空配置拒绝及数据卷身份。
- `test_knowledge_compose.py`、`test_knowledge_vectors.py`、`test_agent_runtime_compose_security.py`：47 passed / 1 skipped（13.29 秒）。跳过的是需要隔离 PostgreSQL/Qdrant 的真实集成测试，本轮未重跑该服务测试。
- 测试分层治理：7 passed；Markdown 链接、新增测试 Ruff、两种实际 Compose config --quiet、OpenSpec strict、git diff --check 通过。
- 本机实际解析配置前后逐服务/网络/卷计算摘要：叠加配置的全部 27 个服务及所有网络/卷与拆分前完全一致，项目名仍为 enterprise_agent。只输出比较结果，不输出解析配置或凭据。
- 对现有 PostgreSQL、Embedding、Qdrant 的容器 ID、启动时间、挂载和网络计算摘要，前后相同。本轮未启动、重建或停止容器，未迁移数据库、生成向量、下载模型或删除数据卷。
- 扩展存储/迁移回归：87 passed / 2 skipped / 11 failed（32.11 秒）。11 条均位于 `test_schema_migration_runtime.py`：工作期间另一项分页变更新增 `135_expand_schema_pagination_cursors.sql`，旧 head/applied/catalog/public 表数量断言仍对应 134。未修改该并行变更或其断言；不能据此报告全库回归通过。后续正式迁移必须重新核对最新 catalog，不能使用历史 head 134 作为部署目标。

本次拆分验收时 change 为 15/18 项完成；5.2–5.4 的正式迁移、全量索引、恢复/重启验收及最终回归仍未完成。

## 范围提交前验收（2026-09-17）

按用户“提交代码”要求，仅暂存本线程知识库实现及配套配置/测试/文档，共 41 个文件。共享事实源清单和迁移测试仅纳入 knowledge migration 134 对应部分；并行分页 migration 135、游标实现及其测试仍留在工作区，不包含在本次提交中，也未覆盖或回退工作文件。

从实际暂存区导出独立源码快照（不含本地 `.env`、真实数据、模型文件或 migration 135），在该快照验收：

- 14 个知识/迁移/Compose/测试治理相关文件：182 passed / 3 skipped（71.97 秒）；另 5 个 schema/架构测试文件：61 passed / 2 subtests passed。合计 243 passed / 3 skipped / 2 subtests passed。三条跳过用例需要隔离 PostgreSQL/Qdrant，本轮未启动集成环境。
- Ruff、两种 Compose 配置、OpenSpec strict、Markdown 链接及暂存区 `git diff --cached --check` 通过。修正了尚未正式应用的 migration 134 文件尾部空行；实际数据库只读核验仍为 head 133。
- MyPy 定向检查 10 个文件时，通过传递导入报出 1 条身份模块错误：`service_principal.py:19` 中 `principal_jwt` 未显式导出 `MAX_PRINCIPAL_TOKEN_BYTES`。单独检查该文件同样复现；这两个身份文件均与 HEAD 相同，不属于本次修改，未扩展修复范围。不能报告 MyPy 全通过。

上节的 11 条失败是当时混合工作区的运行记录，保留不改写；本次独立快照只证明知识库提交在自身 migration 134 边界下回归通过，不代替并行分页变更合并后的验收，也不代表正式全量索引已完成。

## 合并后全量回归修复（2026-09-17）

在 `cd4f66e` 干净工作区的回归发现：后端全量 2394 passed / 2 failed / 41 skipped / 2 subtests passed；真实知识存储补测 2 passed / 1 failed；MyPy 有 1 条常量间接导入错误。用户随后确认修复这四处，不授权正式迁移、业务服务重启或全量索引。

修复范围：

- 业务应用测试移除停留在 130 的重复迁移文件清单，改为核验当前 deployable catalog 的实际应用序列、head 和重复执行无增量。精确文件名/版本/校验和的治理断言仍保留在 `test_schema_migration_runtime.py`，没有删除全局迁移门禁。
- 知识向量真实集成测试不再固定期望 head 134；按当前 deployable catalog 验证实际迁移结果，继续执行向量写入、查询、幂等、丢点恢复、并发锁及数据库约束校验。
- 旧鉴权架构扫描仍覆盖全部生产目录；HS256 唯一例外限定为 Oracle 模块内的 `OracleVerificationTickets` 类，不放行整个模块。新增 8 条扫描/反向用例，证明 Business Principal、Service Principal、业务 MCP、Oracle 模块级代码、其他票据类及类装饰器不被例外放行。其他禁用标识仍检查完整源文本；不修改 Oracle 或 Principal 的运行算法。
- 服务身份的 token 字节上限直接从 `app.shared.principal_token_contract` 导入，值仍为 8 KiB，不修改签发、验证或权限语义。

修复后已验证：

- 定向测试 98 passed / 1 skipped（16.64 秒）。
- 临时 PostgreSQL 18 / Qdrant 1.17 使用独立容器、随机 loopback 端口和 tmpfs，仅含合成数据：三个真实知识存储用例全部通过（3.62 秒）；此前因版本断言提前停止的 Qdrant 分支本次实际执行通过。测试后容器和临时数据已清理，无正式卷挂载。
- Ruff 通过；MyPy 后端全部 431 个源码文件通过。两种 Compose config --quiet、OpenSpec strict、Markdown 链接和 git diff --check 通过。
- 前端 15 个测试文件 / 158 条用例全部通过；lint、typecheck、build 通过。现有 Vite native config 的 `__dirname` 与单个 JS 包超过 500 kB 警告仍在，不属于这四处修复。
- 后端全量复跑：2404 passed / 41 skipped / 2 subtests passed（315.97 秒），无失败。41 条跳过中，三个知识真实存储用例已在上述隔离环境单独执行通过；其余外部验收不能据此视为通过。任务 4.4 完成，change 当前 16/19；5.2–5.4 保持待办。

正式迁移、全量真实语料索引与恢复/重启验收仍未执行，不将上述合成/隔离存储测试当作真实业务 Recall@K 或完整部署验收。

## 已取得证据

- 独立模型镜像完整构建成功；无网络容器内实际导入 Torch `2.14.0+cpu`、Transformers `5.17.0`、Sentence Transformers `6.0.1`；CUDA 不可用。
- PyTorch 使用官方 Linux ARM64 CPython 3.12 CPU wheel（含 SHA256），其余依赖从 PyPI 锁定版本及分发摘要，避免引入 NVIDIA 依赖或 CPU 索引的旧间接依赖。
- Qdrant `v1.17.0` 固定 digest 已在本机启动；仅 internal 网络、无发布端口，2 CPU/2 GiB 限额，观测空库内存约 56 MiB；正式 collection 数为 0。
- 已构建包括 Migrator、API、Worker、MCP、File Service/Processing、Python Runtime 的 head 一致后端镜像；未启动这些业务服务，不代表 API 就绪。
- 只给正在运行的 PostgreSQL 增加知识网络及 `postgres` 别名，未重启数据库。知识 CLI 实际验证可达 PostgreSQL/Qdrant，连接公网 IP 返回不可达。
- 模型容器验证非 root、Hub offline、公网连接返回 ENETUNREACH；只读模型挂载。模型准备任务无环境凭据、无数据库网络或业务卷；CLI 无平台 Secret 挂载。
- SQLite/合成故障测试覆盖：固定清单、分页、多批次、基准、重放、写点后记账前中断、丢点补写、点身份冲突、额外点、不提前 READY、并发锁、来源修订/移除收录过滤、去重逐级补足、向量/响应/请求边界、忙碌、缺模型、错误不回显文本及事务内禁止外部 IO。
- 使用专门的临时 PostgreSQL 18.4 和 Qdrant 容器（只含合成数据）运行真实迁移、约束/类型、实际 collection metadata、`wait=true` 写确认、查询、幂等及丢点恢复测试通过。独立连接的同索引锁互斥通过。Qdrant 重启后两个合成索引的 8 个点逐项核验通过。
- 19 个相关测试文件合并回归：241 passed / 3 skipped / 2 subtests passed（70.06 秒）。其中三个真实环境测试已另行在隔离 PostgreSQL/Qdrant 执行通过；批量回源实现更新后，向量测试含真实用例再次 28 passed（14.57 秒）。临时容器及其纯合成数据已清理，不涉及正式卷。
- Ruff、MyPy（10 个新增生产文件）、Compose config、OpenSpec strict 和 git diff --check 通过；后续变更仍需最终重跑。
- 正式模型容器在文件不完整时实际返回 `/ready` 503、`/profile` 503，仅一条固定 `knowledge_model_unavailable` 启动日志。运行 UID/GID 为 10007:10007、rootfs 只读、4 CPU/8 GiB；未提前推理或联外补文件。
- 完整 10 个文件逐项校验通过，包括 2271145830 bytes 官方 bin 的 SHA256。重新加载约 8 秒后服务 ready/healthy；运行时仍不能连接公网。
- 实际模型合成 smoke：3 个 1024 维向量，范数均为 1.0；相关/无关文本余弦分别 0.93314 / 0.55421，相关文本排序靠前，调用约 0.392 秒。这不是业务 Recall@K。

## 真实语料基准

- 全部 8309 块 token 预检通过：合计 1436282 tokens；min=73、p50=156、p95=276、max=1025（包含特殊 token），没有截断或超限。
- 按文本长度等距分层选取 100 块：107.566 秒，0.930 块/秒，最慢批次 16.847 秒。
- 按该样本线性外推全量约 8938 秒，即 2 小时 29 分；只是当前机器的粗估，不包含正式清单/Qdrant/检查点/验证开销，也不是未来 20 万缺陷的容量结论。
- 本次容器 cgroup v2 `memory.peak` 为 2790801408 bytes（约 2.60 GiB，包含加载及基准），低于 8 GiB 限额；未 OOM，模型服务 healthy。
- 实际基准前后模型日志均 364 bytes、SHA256 `f16a7628ac04c8a25ff838f3221cafb19a92070dd416150546fa17c93ea6e15f`，完全不变；没有随真实 token 预检或编码增加正文/向量日志。
- 基准后原九表行数及下列整表摘要全部不变；正式 head 仍 133，`knowledge.vector_index` 尚不存在，正式 Qdrant collection 数仍为 0。

## 正式来源快照（尚未迁移）

- schema head：133；文档 5000、chunk set 5000、chunk 8309。
- chunk profile：`edd49b9698781b2e473dfae2fcd3410de631a4ddbcc27468cd55bb35ba55fd35`。
- corpus SHA256：`d980c901100a7a751781582fb79c486fd275c65ff6f6eda95f0ae2945e0be5d2`。
- embedding profile SHA256：`595254deaeae70c19815d4b42847cc468790a2742bbdf4b5bd6703cfefcf22f3`。

原九表的整行内容先在 PostgreSQL 内逐行求 MD5，再对排序后的行摘要求 MD5；仅输出计数/摘要，用于前后非破坏性回归核对，不导出真实行：

| 表 | 行数 | 内容摘要 |
|---|---:|---|
| source | 1 | 31a5243c65923e723a3e22cff24ea6c6 |
| document | 5000 | de98a1e31b30314b780f8bc8859bceb2 |
| document_revision | 5000 | fb7b9816af5572c3f6fa054f16fc1bfa |
| knowledge_base | 1 | 15d60bcba9b03e2c7fc8c7076a619dfa |
| knowledge_base_document | 5000 | 1fb525cea82eef90d489e709d1404413 |
| import_run | 1 | ff791d2b005b610a3e1349a2f5455540 |
| document_relation | 2407 | 140f23a804230c937828a949edbf8a4e |
| document_chunk_set | 5000 | 9c2e0fcff6e09120699dab1431763ec8 |
| document_chunk | 8309 | e90c2e116bbcba9e712322a5e610f2b1 |

## 尚未验收

正式迁移到执行时重新核实的 deployable head（须包含知识向量迁移 134，当前代码也已有分页迁移 135）；全量 8309 点构建、逐点核验、重放及重启后的真实语料查询；全量完成后的最终回归与验收记录。无人工标注，不报告真实 Recall@K。
