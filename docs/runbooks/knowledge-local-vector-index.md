# 本机知识向量索引

本轮仅支持本机 Docker Linux ARM64 / Python 3.12、BGE-M3 dense 1024 维和 Qdrant。原始导入及分块入口不自动调用模型。此入口是受控运维 CLI，不是 Agent/MCP/RBAC 授权；知识库仍为 `storage_only`，来源仍可为 `offline_unverified`。

## 数据和安全边界

- PostgreSQL 原九表保留；前向 migration 134 只新增 `knowledge.vector_index` 和 `knowledge.vector_index_item`。
- 模型固定 revision `5617a9f61b028005a4858fdac845db406aefb181`，使用官方 `pytorch_model.bin`，不做 safetensors 转换或 ONNX 导出。加载显式 `weights_only=True`、`trust_remote_code=False`；不增加任意类 allowlist。
- 模型完整清单见 `backend/app/modules/knowledge/embedding_model.json`；CPU 依赖锁按架构分别固定为 `embedding_runtime.lock`（Linux ARM64）和 `embedding_runtime_amd64.lock`（Linux AMD64），PyTorch wheel 各有独立 SHA-256，其余依赖版本与哈希相同。构建时按 `TARGETARCH` 选择并验证 CPU PyTorch；未知架构失败关闭。运行时 Embedding profile 也按架构选择锁的摘要，跨架构迁移不能默用旧索引，须在目标架构重建并核验向量索引。
- 准备容器只下载固定公开模型、校验大小/摘要，无数据库或业务卷/凭据。失败的 `.partial` 不被运行时接纳，重跑不会跳过完整校验。
- Embedding 只读挂载模型卷，关闭 Hub 在线访问、遥测、远程代码；与 Qdrant/CLI 仅接入 internal 网络，无宿主机发布端口。不得通过开放端口把本机方案变为多租户服务。
- 模型服务请求上限 8 条、每条 4096 tokens、合计 8192 tokens，256 KiB 请求体、单并发；只计数端点允许批量总数超过 8192，以便客户端重新组批。所有计数包含特殊 token。服务不静默截断。
- Qdrant 仅存向量与索引/知识库/文档/版本/块 ID、种类和摘要；不存标题、正文、URL 或人员。
- 命令输出仅计数、摘要、固定错误码、引用。禁止打印原文、查询、向量、底层响应、DSN 或解析后的完整 Compose 配置。

## 执行顺序

知识服务只在显式加载 `knowledge/compose.yml` 时存在；完整部署边界见[知识库部署入口](../../knowledge/README.md)。以下命令均在仓库根目录执行，沿用原项目名和数据卷。`DATABASE_DSN` 必须从既有部署配置提供并指向同库 `postgres:5432`；不要打印配置值或复制凭据到扩展文件。

先核对当前运行服务、数据库 head、原九表计数/摘要。不要在旧业务镜像仍运行时直接升级 schema。构建 head 一致的业务镜像不等于已经部署或 API 就绪；不得因本轮任务启动整个业务栈。

```sh
docker compose config --quiet
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge --profile knowledge-prepare config --quiet
docker compose -f docker-compose.yml -f knowledge/compose.yml --progress quiet build knowledge-embedding knowledge-ops
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge-prepare run --rm --no-deps knowledge-model-prepare
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge up -d --no-deps knowledge-embedding knowledge-qdrant
```

PostgreSQL 需加入 `knowledge-internal` 并具有 `postgres` 网络别名。首次部署通常由 Compose 管理；若既有数据库持续运行，应在维护流程下仅附加新增网络，不能为了准备基准重建数据库。配置已声明该网络，模型/CLI 不应再加入默认网络。

```sh
# 只读全量 token 预检，并对按长度分层选出的 100 块做本地基准；不写 Qdrant。
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge run --rm --no-deps knowledge-ops \
  python -m app.cli.index_knowledge --index-code ones-defects-bge-m3-v1 --benchmark
```

默认期望 5000 个当前收录文档、8309 个块和已接受的分块 profile。数量变化必须确认新语料，不要为了让命令通过而任意修改期望值。基准前后核对语料摘要；记录 token 分布、实际耗时、吞吐和容器内存。超限、OOM、模型不一致必须停下处理，不能截断或接入外部模型。

仅在镜像/迁移窗口及基准确认后，通过正常 one-shot Migrator 更新到当前 deployable head（必须包含知识向量迁移 134）；若其他变更新增后续迁移，须重新核对 catalog 和镜像，不能仍按历史 head 134 部署。知识 CLI 不执行 DDL，也不自动创建业务配置或授权。

```sh
# 显式提交。相同命令用于断点恢复及全量重放核验。
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge run --rm --no-deps knowledge-ops \
  python -m app.cli.index_knowledge --index-code ones-defects-bge-m3-v1 --commit

# 从 stdin 输入，避免查询进入命令参数；输出只含回源核验过的定位引用。
docker compose -f docker-compose.yml -f knowledge/compose.yml --profile knowledge run --rm -T --no-deps knowledge-ops \
  python -m app.cli.query_knowledge --knowledge-base-code ones-defects-offline \
  --index-code ones-defects-bge-m3-v1 --top-k 10
```

查询最多 2000 字、top-k 为 1–20；输入完发送 EOF。先验证 READY、知识库和模型版本，再最多取 200 个向量候选，回 PostgreSQL 校验当前版本/收录/文本摘要，文档去重后最多返回每文档 3 个证据定位；不足时 `partial=true`。此行为不能代替后续用户级授权。

## 恢复与版本

索引代码绑定固定语料和配置，一个版本一个独立 collection；不静默扩充现有索引。变更语料、chunk profile、模型/依赖时使用新的明确版本，保留旧集合。清理需要另行批准。

单索引会话级锁覆盖清单构造和构建；数据库事务只包短写，不跨模型/Qdrant IO。清单完整后才开始推理。每点由索引 UUID 与块 UUID 确定；Qdrant 必须 `wait=true` 确认后才记账。写点成功但未记账时，重跑核对点身份后补记；数据库已记账但点缺失时补写。点身份、集合所有权、维数/距离不匹配立即停止，绝不清空其他集合。

全部预期 ID、payload、向量形状、集合 exact count、来源版本/收录/摘要均核验通过才 READY。失败保留检查点和卷；重跑 `--commit` 恢复。完成后核对原九表摘要不变、重放 `encoded=0`、重启后点仍存在。

## 验收边界

合成故障/真实 PostgreSQL 与 Qdrant 接口测试证明存储协议；模型合成 smoke 和原文自查询只证明计算/检索链路。没有人工相关性标注时不能报告真实 Recall@10 或 MRR。OCR、附件下载、在线采集/定时增量、Web、MCP/RBAC、混合召回和 Reranker 均不在本轮。

### 2026-09-17 本机验收快照

- 正式 schema head 135；`ones-defects-bge-m3-v1` 已对 5000 个文档的 8309 块完成构建并逐点核验至 READY，原九表数量/内容摘要不变。
- 首次启动至完成约 2 小时 24 分钟，包含一次中断恢复；模型容器累计峰值约 2.87 GiB（含加载和此前基准），不是未来大规模部署的容量承诺。
- 全量重放 `encoded=0 / reused=8309`；仅知识服务重启后全部 8309 点仍通过身份、数量及来源校验。未重启 PostgreSQL 或删除正式数据。
- CLI 合成查询成功；按长度分层取 10 条原文自查询均在首位找回对应文档，仅证明计算与检索链路，不是人工标注业务召回评测。

此处是上述日期的运行证据，不是长期健康承诺。后续变更语料或配置前，仍须按本手册重新核对版本、数量与来源；不能据此直接启用 Agent/MCP 权限。

## Qdrant 版本升级与恢复

当前可选知识 Compose 固定 `qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`，2026-09-18 已在本机 Linux ARM64 正式运行验证。镜像摘要与 image ID 是不同对象，不能互相替代；版本标签为空也不能据此判断镜像无用。

已有数据必须遵循 [Qdrant 官方升级路径](https://qdrant.tech/documentation/upgrades/)，单节点也不能跳过中间次版本。本次执行 `1.17.0 → 1.17.1 → 1.18.3 → 1.19.1`，每一级使用明确版本和摘要；先在冷备复制出的隔离卷验证，再仅对 `knowledge-qdrant` 使用 Compose `up -d --no-deps --pull never`。未重启 PostgreSQL、Embedding 或业务服务，未执行 DDL、重新向量化或授权发布。

### 2026-09-18 升级验收

- 正式容器实际二进制为 `qdrant 1.19.1`；保留原卷 `enterprise_agent_knowledge-qdrant`、internal 网络和无宿主机端口边界。
- 冷备文件摘要匹配，并在独立卷用 1.17.0 启动证明可恢复；演练与正式各级升级、最终重启后的 8309 个点/向量摘要及集合关键配置均与升级前一致。
- 现有应用客户端逐点匹配 PostgreSQL 索引清单：5000 文档、8309 点、READY；本地 Embedding 合成查询返回 10 条，命中文档顺序摘要一致。5 个向量自查询探针全部在 top 10 找回自身，结果序列也一致。
- 本次核验未读取真实 ONES，不代表 Agent/MCP/角色授权或业务召回率验收。
- 当时正式 schema 已为 136，原 `knowledge-ops` 镜像仍落后并触发 schema 门禁。只读应用核验使用主栈现有的当前 `enterprise_agent-migrator` 镜像；没有绕过门禁、执行迁移或顺带重建业务镜像。后续运行默认 knowledge-ops 前应按当前 catalog 重建/验收运维镜像。

### 保留的恢复点

- 本机冷备卷：`enterprise_agent_qdrant_backup_1170_20260918_ynsbow`，约 83 MiB，未挂到常驻服务，不自动删除。
- 对应原镜像：`qdrant/qdrant:v1.17.0@sha256:f1c7272cdac52b38c1a0e89313922d940ba50afd90d593a1605dbbc214e66ffb`。
- 文件内容清单 SHA-256：`6ef9de07a8be77224d16d191d30227ae6242af071a68e04a698d61f77b065cc8`（按相对路径排序后，对各文件 SHA-256 清单再取摘要）。
- 演练容器与专用演练卷已清理；正式卷、冷备卷、原镜像保留。冷备属于本机恢复点，不是异地备份。

回退必须先停止知识写入，确认后续数据变化及恢复窗口，从冷备复制到一个新的明确恢复卷，用对应 1.17.0 镜像隔离验证，再在维护窗口定向切换。不得用旧镜像直接打开已被 1.19.1 迁移的正式卷，也不得覆盖冷备或使用 `down -v`。有升级后新增写入时，不能未经核对直接回退到本恢复点。

升级验收当时 Docker 可用磁盘约 0.7 GiB，需要另行规划扩容或明确范围的清理；本次没有删除其他项目镜像、卷或旧验收容器。

## 运维镜像更新与定向重启

`knowledge-ops` 使用与平台一致的 migration catalog，但其本机镜像不会随主栈镜像自动刷新。数据库已升级而旧 CLI 报 `knowledge_schema_head_mismatch` 时，先核对仓库 catalog 与已部署版本，再定向构建；不要关闭门禁或为了旧镜像降级数据库。

```sh
# 只更新一次性运维镜像，不更新模型或其他服务。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --profile knowledge --progress quiet build knowledge-ops

# 仅在需要维护重启时执行；保留模型/向量卷，不重启 PostgreSQL。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --profile knowledge restart knowledge-qdrant knowledge-embedding
```

先确认没有运行中的索引写入任务，并等待 Qdrant `/readyz`、Embedding `/ready` 就绪，再按上文查询命令使用默认 `knowledge-ops` 镜像验证 schema 门禁与本地检索。`knowledge-ops` 没有常驻进程，无需 `up` 或 `restart`；以 `run --rm --no-deps` 重新运行明确的一次性命令即可。运维镜像刷新不需要 `--commit`、模型准备任务或数据库迁移。

### 2026-09-18 运维镜像刷新验收

用户授权后已定向构建默认 `knowledge-ops`，镜像内 catalog 包含 migration 136；上文记录的旧镜像门禁失败已解决。Qdrant/Embedding 已定向重启并就绪，默认运维镜像无需临时覆盖即可通过 schema 门禁、5000 文档/8309 点身份核验及合成问题检索；点/向量和命中序列摘要保持不变。其他 23 个既有容器身份和启动时间未变，没有迁移、重新索引或删除恢复点。当前 Docker 数据盘约 1.4 GiB 可用（98% 已用），容量维护仍需单独安排。
