# 本机知识向量索引

本轮仅支持本机 Docker Linux ARM64 / Python 3.12、BGE-M3 dense 1024 维和 Qdrant。原始导入及分块入口不自动调用模型。此入口是受控运维 CLI，不是 Agent/MCP/RBAC 授权；知识库仍为 `storage_only`，来源仍可为 `offline_unverified`。

## 数据和安全边界

- PostgreSQL 原九表保留；前向 migration 134 只新增 `knowledge.vector_index` 和 `knowledge.vector_index_item`。
- 模型固定 revision `5617a9f61b028005a4858fdac845db406aefb181`，使用官方 `pytorch_model.bin`，不做 safetensors 转换或 ONNX 导出。加载显式 `weights_only=True`、`trust_remote_code=False`；不增加任意类 allowlist。
- 模型完整清单见 `backend/app/modules/knowledge/embedding_model.json`；独立依赖锁包含 CPU 专用 wheel、精确版本及分发哈希。现有锁仅用于 Linux ARM64，其他架构必须重新验收，不能直接替换 wheel。
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
