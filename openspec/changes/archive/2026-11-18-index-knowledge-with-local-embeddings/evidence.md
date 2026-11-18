# 实现与运行验收（2026-09-17；持续更新）

## 当前边界

用户同意继续后，采用官方固定 PyTorch bin 的受限加载，不转换、不用 ONNX。已完成代码、ARM64 CPU 镜像、全部官方文件校验、实际离线推理、全量 token 预检和 100 块真实基准。2026-09-17 用户再次要求 apply 继续后，正式数据库已迁移到 head 135，并明确选择后台运行及自动跟进。14:26 UTC 全量 8309 点构建及逐点核验完成、状态 READY，随后全量零编码重放、知识服务重启、重启后逐点核验及合成/原文自查询全部通过；最终原九表数量及内容摘要不变。以下进度快照属于历史过程，不代表当前仍在 BUILDING。

未改变 `storage_only` / `offline_unverified`，未启用 Web、MCP、用户授权、OCR、采集或外部推理。

任务 5.2–5.4 均已真实验收，整体 19/19。自动跟进“知识库全量索引与验收跟进”（ID `automation`）已通过应用工具暂停，并核对本地状态为 PAUSED；未停用知识服务或删除运行证据。变更尚未归档，文档改动尚未提交。

## 正式迁移与后台索引过程（2026-09-17，已完成）

- 执行前工作区为 `18e94f2` 且干净；本机仅 PostgreSQL、Embedding、Qdrant 三个容器运行，没有业务服务容器。Agent Job 只有 204 个 SUCCEEDED、9 个 FAILED；文件处理只有 76 个 SUCCEEDED、3 个 PARTIAL、1 个 FAILED，无非终态处理任务或其他活跃数据库语句。
- 运行数据库为 head 133；旧 Migrator/knowledge-ops 镜像为 head 134。本轮仅重建这两个一次性镜像到 head 135，安装包名称/版本摘要与旧镜像完全一致：`0be8a0a9180cb5edf1b208f1fe36fdeca0195823f7e475308959867835c8d1e7`。没有启动或重建业务全栈；其后续部署必须重新构建与当前 schema 一致的镜像，不能用历史镜像直接启动，也未声称 API 就绪。
- 正式执行 one-shot Migrator，build 为 `knowledge-index-18e94f2-20260917`：`head=135 baselined=0 applied=134,135`；立即重放为 `applied=-`。134 新增两个 knowledge 向量协调表，135 新增 public 分页游标表。没有回退或修改旧迁移、没有清理业务数据。
- 迁移前后原九表计数与整表内容摘要逐项相同，与下文历史来源快照也全部一致。重新全量只读预检仍为 5000 文档、8309 块；corpus/profile/token 分布与先前基准完全相同，无超限或截断。
- 2026-09-17 12:01:55 UTC 启动后台容器 `enterprise_agent-knowledge-index-20260917`，使用显式叠加 Compose、索引 `ones-defects-bge-m3-v1` 和 `--commit`。容器无自动重启策略，保留安全进度日志；索引仍为 BUILDING，不能作为 READY 查询入口。
- 为验收进程中断恢复，在前几个批次后只停止上述索引容器；停止超时终止退出码为 137，但 `OOMKilled=false`。停止后 128 条 INDEXED 检查点和 8181 条 PENDING 保留，advisory lock 为零，Qdrant 专属集合保留 128 点。12:05:19 UTC 重启同一容器与相同命令，未更换索引版本、清空集合或重启数据库。恢复后达到 `processed=128, encoded=0, reused=128`，随后继续到 `processed=160, encoded=32, reused=128`，确认没有重算或重复新增前 128 点；全量完成后的重放/重启验收仍待执行。
- Embedding 与 Qdrant 仍仅接入 `internal=true` 的知识网络且无公开端口。真实推理期间模型日志 SHA256 仍为 `f16a7628ac04c8a25ff838f3221cafb19a92070dd416150546fa17c93ea6e15f`，与基准日志相同；仅读取安全计数/摘要，没有把文本或向量打印到会话。
- 本轮相关五个测试文件 136 passed / 3 skipped（50.37 秒）；三条跳过均需独立真实存储环境，不能算本轮重新通过。Ruff、MyPy 全部 431 源文件、叠加 Compose config、OpenSpec strict 及 diff 检查通过。这是运行期间的检查，不替代全量完成后的最终验收。
- 用户明确选择后台运行并自动跟进，已创建当前线程每 15 分钟的自动跟进“知识库全量索引与验收跟进”（ID `automation`）。后续检查进度并在完成后继续原九表核验、全量重放、仅知识服务重启及受限检索；遇到漂移或需扩大范围时暂停请求用户决定，完成后停止自动跟进。没有授权自动提交、推送或归档。

启动时任务 5.2–5.4 保持未勾选、整体为 16/19；正式迁移完成不等于全量索引完成，后续验收结果见下文。

### 后台跟进快照：2026-09-17 12:23 UTC

索引容器继续运行，最新整批进度为 1184/8309（新编码 1056、复用 128）；随后 PostgreSQL 检查点为 INDEXED 1192、PENDING 7117，无 FAILED，索引状态 BUILDING、无错误码、schema head 135。两处计数采样时间不同且写入仍在进行，不将整批日志与逐 8 条检查点的瞬时差异当作缺点。Embedding healthy、约 4 核占用且内存约 850 MiB/8 GiB；Qdrant 约 83.9 MiB/2 GiB，各容器 OOMKilled=false。最近连续批次进度增长，未重复启动写者、未重启服务，继续等待下轮自动跟进；没有提前执行全量重放或勾选任务。

### 后台跟进快照：2026-09-17 12:40 UTC

PostgreSQL 检查点增至 INDEXED 2184、PENDING 6125（26.3%），无 FAILED；整批日志连续从 2080 增长到 2176，仍复用原 128 点。索引保持 BUILDING、无错误码，schema head 135。Embedding healthy、约 4 核、865.4 MiB/8 GiB；Qdrant 89.69 MiB/2 GiB；各容器 OOMKilled=false。本轮仅观察并记录，无重启、重复写者或提前验收，继续自动跟进。

### 后台跟进快照：2026-09-17 12:56 UTC

PostgreSQL 检查点为 INDEXED 3120、PENDING 5189（37.5%），无 FAILED；最近整批日志从 3008 连续增长到 3104，复用仍为 128。索引 BUILDING、无错误码，schema head 135，三个知识相关容器均运行且 OOMKilled=false。Embedding healthy，约 4 核、当前 841.7 MiB/8 GiB，容器自启动累计 memory.peak 为 3081728000 bytes（约 2.87 GiB，包含先前基准和本轮运行）；Qdrant 当前 94.65 MiB/2 GiB。继续正常构建，本轮无新增写者、无重启，5.2–5.4 继续待验收。

### 后台跟进快照：2026-09-17 13:13 UTC

PostgreSQL 检查点增至 INDEXED 4112、PENDING 4197（49.5%），无 FAILED；最新整批日志连续从 4000 增长到 4096，复用 128 点。索引 BUILDING、无错误码，schema head 135。Embedding healthy，约 4 核、859.5 MiB/8 GiB；Qdrant 100.1 MiB/2 GiB；索引、Embedding 和 Qdrant 均运行且 OOMKilled=false。构建持续推进，保持原写者运行，不启动全量重放或重启；spec-driven 任务进度仍为 16/19。

### 后台跟进快照：2026-09-17 13:33 UTC

PostgreSQL 检查点增至 INDEXED 5224、PENDING 3085（62.9%），无 FAILED；最新整批日志连续从 5120 增长到 5216，其中编码 5088、复用 128 点。索引 BUILDING、无错误码，schema head 135。Embedding healthy，约 4 核、878.9 MiB/8 GiB；Qdrant 127.7 MiB/2 GiB；索引、Embedding 和 Qdrant 均运行且 OOMKilled=false。构建持续推进，保持原写者运行，不启动全量重放或重启；spec-driven 任务进度仍为 16/19。

### 后台跟进快照：2026-09-17 13:49 UTC

PostgreSQL 检查点增至 INDEXED 6152、PENDING 2157（74.0%），无 FAILED；最新整批日志连续从 6048 增长到 6144，其中编码 6016、复用 128 点。索引 BUILDING、无错误码，schema head 135。Embedding healthy，约 4 核、864.3 MiB/8 GiB；Qdrant 133 MiB/2 GiB；索引、Embedding 和 Qdrant 均运行且 OOMKilled=false。保持原写者继续构建，本轮未重启服务、启动重复写者或提前执行验收；任务仍为 16/19，自动跟进保持运行。

### 后台跟进快照：2026-09-17 14:06 UTC

PostgreSQL 检查点增至 INDEXED 7192、PENDING 1117（86.6%），无 FAILED；最新整批日志连续从 7072 增长到 7168，其中编码 7040、复用 128 点。索引 BUILDING、无错误码，schema head 135。Embedding healthy，约 4 核、845.7 MiB/8 GiB；Qdrant 138.9 MiB/2 GiB；索引、Embedding 和 Qdrant 均运行且 OOMKilled=false。继续等待现有写者完成，本轮未启动重复写者、未重启服务、未提前执行全量重放或检索验收；任务仍为 16/19，自动跟进保持运行。

### 正式全量构建完成：2026-09-17 14:26 UTC

- 索引容器于 14:26:13 UTC 成功退出，exit=0、OOMKilled=false；最终 READY，逐项核验 8309 点，编码 8181、复用中断前的 128 点。PostgreSQL 为 5000 文档/8309 块、全部 8309 条 INDEXED，无错误码，退出后 advisory lock 为零。
- 最终 corpus/profile 摘要与上述基线相同；构建内部逐点检查身份和向量形状、核对 Qdrant exact count=8309 并重新检查当前来源后才置为 READY。构建完成后再次计算原九表数量及整表摘要，全部与历史基线一致。
- 恢复后 build 阶段实测 8429.124 秒；从首次启动至成功退出的墙钟时间约 2 小时 24 分 19 秒，包含一次受控中断、恢复和预检。Embedding 累计 memory.peak 为 3081728000 bytes（约 2.87 GiB，包含加载和此前基准），未 OOM；正式推理后日志摘要仍与基准一致。
- 本轮相关六个测试文件 146 passed / 3 skipped（50.95 秒）；三条跳过为未配置隔离存储环境的用例，不计为本轮重新通过。Ruff、MyPy 431 文件、叠加 Compose config、Markdown 链接、OpenSpec strict 和 diff 检查已通过，交付前将再次核对文档与状态。

任务 5.2 完成，进度为 17/19；5.3 的全量重放、知识服务重启和检索验收正在继续，尚不视为完成。

### 全量重放、重启与检索验收：2026-09-17 14:30 UTC

- 原索引写者成功退出后，启动同参数的独立重放容器 `enterprise_agent-knowledge-replay-20260917`；14:28:35 UTC 成功退出，exit=0、OOMKilled=false。结果 READY、verified=8309、encoded=0、reused=8309，build 阶段 46.294 秒，连同预检的容器墙钟约 71.058 秒；没有新建索引版本或增加重复点。
- 确认两个写者均已退出、advisory lock=0 后，仅通过叠加 Compose 重启 knowledge-embedding 和 knowledge-qdrant；二者启动于 14:28:55 UTC，模型恢复 healthy。PostgreSQL 启动时间仍为 2026-09-16 15:09:11 UTC，未重启；模型及 Qdrant 沿用原卷、内部网络和无公开端口配置。
- 重启后执行只读验收：逐项核验全部 8309 点的身份与向量形状、collection 配置和 exact count，以及当前来源快照，全部通过，核验耗时 18.355 秒。未删除正式点来模拟故障；正式中断恢复证据见前述 128 点复用，写点后未记账/丢点修复/冲突拒绝由既有合成及隔离真实存储测试覆盖。
- 在知识运维容器内，从 8309 个符合查询长度上限的块按长度等距取 10 个原文自查询，原文不离开内部网络、不打印或落盘；10/10 在第 1 位找回对应文档，均无 partial，最多检查 40 候选，共 16.397 秒。匹配分数范围 1.0–1.0000001，浮点误差内的相似度，不解释为置信度。
- 通过正式 query CLI 的 stdin 运行合成查询，成功返回 3 个不同文档、20 候选、partial=false；输出仅引用、分数及证据位置，无正文。这些 smoke 只证明计算和回源检索链路，尚无人工标注集，业务 Recall@10/MRR 未验证。

任务 5.3 完成，进度为 18/19；继续最终回归与交付记录检查。

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

## 正式来源快照（迁移前历史基线）

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

## 最终交付检查

- 在全量构建、重放、重启和检索完成后重新运行上述六个相关测试文件：146 passed / 3 skipped（46.69 秒），无失败；跳过用例仍为隔离真实存储测试，不能报告为本轮重跑通过。此前已通过的隔离存储和全库回归证据保留在历史章节，不与本轮结果混计。
- Ruff、MyPy 后端全部 431 个源码文件和显式叠加 Compose config 再次通过；OpenSpec strict、Markdown 链接与最终 diff 检查全部通过。
- 重放和检索后原九表数量及摘要再次全部等于迁移前基线；模型在本次重启后验收时段（14:29:40 UTC 起）的新增日志为 0 bytes。未输出真实正文、查询或向量，未调用真实 ONES 或外部 Embedding。
- 仅修改本 change 的任务/验收记录及运行手册，没有追加生产代码、迁移、授权或业务配置。正式索引和重放容器成功退出后保留以供查看安全日志；未删除集合、点、原数据或正式卷，没有提交、推送、同步或归档任何 change。

## 未包含及待业务验收

本轮已完成正式本机向量索引与受限运维检索验收。尚无人工标注集，业务 Recall@10/MRR 未验证；合成查询和 10 条原文自查询不能代替真实用户问法的效果评估。未包含 Web/MCP/用户授权、混合召回与重排、OCR/附件下载、在线采集及定时增量；来源仍为 offline_unverified、知识库仍为 storage_only。未启动业务全栈、未验收 API 就绪，也未承诺未来 20 万缺陷的生产容量；后续业务部署须使用与 schema head 135 一致的镜像。
