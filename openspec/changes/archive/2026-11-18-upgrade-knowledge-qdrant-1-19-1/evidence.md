# Qdrant v1.19.1 本机升级证据

执行日期：2026-09-18。用户明确授权“升级到 v1.19.1，然后固定”。本记录只包含版本、数量、摘要和对象身份，不含业务正文、查询向量或凭据。

## 范围与环境

- 仓库：`/Users/mhz/Develop/enterprise_agent`；Docker context：`desktop-linux`；镜像平台：Linux ARM64。
- 正式服务：`enterprise_agent-knowledge-qdrant-1`；正式卷：`enterprise_agent_knowledge-qdrant`。
- 当前应用 schema 136；本次未执行任何 PostgreSQL DDL/迁移或索引写入。
- 升级前未发现运行中的 knowledge-ops 索引容器，索引为 READY 且 BUILDING 索引计数为零。旧索引/重放容器均为此前已退出状态，未删除。
- 其他 26 个既有项目容器的 ID/启动时间逐项比较未变化，包含 PostgreSQL 和 Embedding。

## 镜像与路径

| 版本 | 固定 registry digest | 验证 |
| --- | --- | --- |
| 1.17.0 | `sha256:f1c7272cdac52b38c1a0e89313922d940ba50afd90d593a1605dbbc214e66ffb` | 原运行、冷备恢复 |
| 1.17.1 | `sha256:94728574965d17c6485dd361aa3c0818b325b9016dac5ea6afec7b4b2700865f` | 演练、正式 |
| 1.18.3 | `sha256:0bd98fa7977f1e75694779359ca4e212822e5a71334e28421182f72f209d5286` | 演练、正式 |
| 1.19.1 | `sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` | 演练、正式、正式重启 |

目标运行 image ID：`sha256:76beb9a87e28abb463fe00f35a8fe88adcf34dff5e4986880966fb3e6b67c7e5`，与固定目标 digest 的本机解析一致。实际 `/qdrant/qdrant --version` 返回 `qdrant 1.19.1`，`/readyz` 成功、集合 green。Compose 中已保存版本号和 digest，运行无端口映射。

升级依据：[Qdrant 官方升级说明](https://qdrant.tech/documentation/upgrades/)，单节点同样要求逐个次版本应用数据迁移。未从 1.17.0 直接跳到 1.19.1。

## 恢复点与隔离演练

1. 短暂停止正式 Qdrant，原卷只读挂载，从空的任务专属卷接收完整冷备，文件比较及摘要相等后立即恢复正式原版。
2. 保留冷备卷 `enterprise_agent_qdrant_backup_1170_20260918_ynsbow`，约 83 MiB；源与冷备文件清单摘要均为 `6ef9de07a8be77224d16d191d30227ae6242af071a68e04a698d61f77b065cc8`。
3. 冷备只读复制到 `enterprise_agent_qdrant_rehearsal_20260918_ynsbow`，由专用 `knowledge-qdrant-upgrade-check` 容器先用原版启动验证恢复，再逐级演练。无公开端口、无业务凭据、遥测关闭。
4. 演练全部通过后，正式 Compose 使用临时中间版本覆盖文件定向升级，最终直接使用根 Compose 与 `knowledge/compose.yml`。未改正式卷名，未重建索引。
5. 最终验收后仅移除了专用演练容器和演练副本；冷备卷及正式卷保留。恢复时从冷备复制新卷并使用原版，禁止原地降级已迁移卷。

## 数据和检索核验

原版、冷备恢复、演练每一级、正式每一级及最终重启的下列摘要完全一致：

| 检查项 | 结果 |
| --- | --- |
| 集合精确点数 | 8309 |
| 全量 point ID / payload / float32 vector SHA-256 | `b3ed11baeaafc2dad14469e3a85d413910a12e9f5bb2655748f5c6a50a8de563` |
| 集合维数、距离、metadata、payload index 类型 SHA-256 | `8f1234cb60ad743c1b3210d5b46b3febf8c679b2387e7844a220f4e265d160ee` |
| 5 条固定向量探针命中序列 SHA-256 | `ec44902ee84bcc4f0aa0e768a8fa27c3120d68f3646f7b12eac328288ec2f836` |
| 向量探针 top 10 找回自身 | 5/5 |

向量只在受限检查进程内按 float32 计算摘要，没有打印或导出。读请求每页 32 点，检查唯一 ID、维数、有限值和归一化；未执行 upsert/删除/collection 重建。

升级前和最终重启后的现有应用客户端核验相同：

- schema 门禁通过，索引 READY，PostgreSQL 当前有效文档 5000、INDEXED 项逐点验证 8309；未读取正文用于构建新的向量。
- 数据库与 Qdrant 预期 payload 身份摘要：`16e6774611a214968bbe1dff31f9bf1ef7c2e1ca116cdc67e5b16af27f0c5298`。
- corpus hash：`d980c901100a7a751781582fb79c486fd275c65ff6f6eda95f0ae2945e0be5d2`。
- embedding profile hash：`595254deaeae70c19815d4b42847cc468790a2742bbdf4b5bd6703cfefcf22f3`。
- 本地 Embedding 合成问题检索返回 10 条，命中文档顺序摘要：`5593fe87c9dc37b77a8a0e563a0c2ded52cc22c176ed73fd08087b9fd5955ca0`。

## 工程回归

- 为既有已分类文件 `backend/tests/test_knowledge_compose.py` 增加固定 v1.19.1/digest、原卷、无端口、internal 网络和关闭遥测断言。修改 Compose 前该测试按预期失败，固定版本后通过。
- `.venv/bin/pytest -q backend/tests/test_knowledge_compose.py backend/tests/test_knowledge_vectors.py backend/tests/test_knowledge_chunks.py backend/tests/test_knowledge_import.py`：87 passed、3 skipped（32.79 秒）。
- 3 个跳过项需要显式隔离 PostgreSQL/Qdrant 测试端点；没有把测试写入正式数据库。另行执行的本机正式只读核验与隔离卷升级/恢复证据如上，不把它们冒充该 3 项测试通过。
- Ruff 检查修改后的 Compose 测试通过。主 Compose 与可选知识 Compose 配置校验、OpenSpec 严格校验、本次修改范围的 Markdown 链接及差异检查均通过。
- 全仓库 Markdown 链接检查另有 1 项未通过：并行工作中的 `docs/development/mcp-inspector.md:75` 引用了当时尚未创建的 `openspec/changes/add-mcp-inspector-smoke-tests/evidence.md`。不属于本次修改，未补建、删除或改写该并行文档；未把全仓库检查记为通过。

## 已识别的既有问题与验收边界

- 原 `enterprise_agent-knowledge-ops` 镜像的 catalog 落后于当前 schema 136，首次只读兼容检查被 SchemaHeadError 阻止。使用当前主栈 `enterprise_agent-migrator` 镜像的临时 Compose 覆盖完成核验；没有关闭门禁或修改数据库。默认旧运维镜像未在本次重建，后续 CLI 运维应先更新其镜像。
- 仅验证本地 Qdrant 数据升级和检索兼容性，没有真实 ONES 请求、Agent 新 Job、MCP/RBAC 或人工相关性验收。
- Docker 升级前可用空间约 1.1 GB，全部镜像就绪后约 853 MB，清理本次演练副本后约 766 MB。保留冷备，不清理无关镜像/卷；后续应单独规划空间维护。
- 并行 MCP Inspector 工作区变动未修改、暂存或提交。本次变更未提交、未推送、未归档。

## 2026-09-18 后续：运维镜像刷新与知识服务重启

用户随后明确要求“更新镜像重启服务”。本节是后续独立验收，不改写上节旧镜像失败的历史证据。

- 仅执行既有 Compose 的 `build knowledge-ops`，复用构建缓存；没有更新基础镜像、模型或业务主栈。构建首次被本机 Buildx 缓存目录写权限阻止，获准后重试成功。
- 默认 `enterprise_agent-knowledge-ops:latest` image ID 从 `sha256:188c97ab11cfc7a8893298d47e74e2e4eb6de608ceb03a1a4ef903b045f2a96c` 更新为 `sha256:c0153d92645402655654af0ab42a4cd97ce3c666089ee19bd89added1cf59bf0`。镜像内 catalog 包含 `136_expand_sandbox_v2_capacity.sql`，知识模块导入正常。
- 使用默认运维镜像（未加载临时 migrator image 覆盖），重启前后各执行一次只读 schema/数据/检索核验：schema 门禁通过，索引 READY、BUILDING 计数零、5000 文档、8309 点。身份、corpus、profile 和合成问题命中序列摘要均与上文一致。
- 仅执行 `restart knowledge-qdrant knowledge-embedding`。Qdrant 启动时间为 `2026-09-18T08:34:06.886253092Z`，Embedding 为 `2026-09-18T08:34:07.651562842Z`；分别通过 `/readyz` 与 healthcheck。`knowledge-ops` 以一次性 `run --rm --no-deps` 运行，无常驻容器需要重启。
- Qdrant 仍为固定 v1.19.1/image ID，原卷和无公开端口边界不变；重启后全部 8309 点的 ID/payload/float32 向量摘要、集合配置、5 个探针命中序列与升级基线完全一致。
- 以本次刷新前的新快照比较，其他 23 个既有项目容器的 ID 和启动时间均未变；没有重启 PostgreSQL、运行迁移、重新索引、准备模型或修改授权。升级前冷备卷仍存在。
- `.venv/bin/pytest -q backend/tests/test_knowledge_compose.py`：11 passed（1.31 秒）。主/知识 Compose 配置、全仓库 Markdown 链接、OpenSpec 严格校验、差异检查通过。全仓库链接检查此次通过，不代表上节历史失败未发生；未修改并行 MCP Inspector 文件。
- Docker 数据盘当前约 1.4 GiB 可用、使用率 98%；本次未删除任何镜像、数据卷或恢复点。仍须单独规划容量维护。
- 本轮仍仅是本机运维/检索验收，不等于真实 ONES、Agent/MCP 授权或业务相关性验收。未提交、未推送、未归档。
