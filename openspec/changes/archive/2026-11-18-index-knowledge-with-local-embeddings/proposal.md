## Why

现有知识模块已生成可追溯的分块和 embedding_text，但尚不能执行向量检索。用户已确认缺陷文本只在本地/内网处理、Qdrant 使用本机 Docker；本轮先建立可恢复的向量索引与本地检索验证闭环。

## What Changes

- 增加可选的独立本地 Embedding 服务，拟使用 BAAI/bge-m3 的 dense embedding；模型文件预下载，推理阶段离线、无公网回退，不安装模型依赖到现有 API/Worker 镜像。
- 增加 Docker 内部网络中的 Qdrant 和持久数据卷；不默认公开管理端口或对外服务。
- 知识服务及专用网络/数据卷放在 `knowledge/compose.yml`，仅通过显式叠加根 Compose 启用；主文件不包含知识服务或知识网络。保持同一 Compose 项目和 PostgreSQL schema，不拆分迁移体系。
- 在同一 PostgreSQL 的 knowledge schema 增加索引清单及逐块检查点，记录模型/规则版本、集合、输入摘要和写入状态；不复制向量到 PostgreSQL，不修改已有来源或分块。
- 增加显式索引 CLI：只读预检、小规模基准、全量提交、重复运行/故障恢复和完整性核验。默认目标为此前验收的 5,000 个文档、8,309 个块，执行前重新核验。
- 增加仅供本机运维的检索验证 CLI；查询和文档使用同一模型配置，召回后回 PostgreSQL 检查当前版本与有效收录，按文档合并多块结果。
- 不实现在线采集、OCR、稀疏混合召回、重排、Web 配置、Agent/MCP 发布、角色授权或任务调度；不把本地可检索当成已对用户授权。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `platform-operations`：增加本地知识向量化、离线推理边界、可恢复索引与受限检索验收要求。

## Impact

- 新增独立模型服务目录/镜像、Compose 可选服务与内部网络、模型文件准备脚本及锁定依赖；现有业务镜像不引入 PyTorch 等大依赖。
- backend knowledge 模块、内部 CLI、下一可用前向迁移、schema 事实源清单及合成/真实服务测试。
- 本机 Docker 当前为 aarch64，分配 10 个逻辑 CPU、约 15.6 GiB 内存。实际吞吐和峰值内存尚未测量；先小样本基准再全量，不能将本机验证承诺为未来 20 万缺陷的生产容量。
- 当前代码已存在 chunk_set/chunk 两表，而 canonical 的七表描述尚未同步：这是已完成的 `prepare-ones-knowledge-chunks` change 的独立规范差异。本 change 以其代码产物为实现前提，不在本轮静默归档、改写或重复接管其 delta。
- 本提案待用户确认后进入 apply。本轮不下载权重、不启动新服务、不执行 DDL、Embedding 或 Qdrant 写入。
