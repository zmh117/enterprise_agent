## Context

用户已选择本地/内网 Embedding，缺陷文本不外发，Qdrant 在本机 Docker 验证。当前实现包含清洗分块及 PostgreSQL 派生存储，未包含 Embedding 客户端、服务或 Qdrant 配置。上一阶段实际验收为 5,000 个文档、8,309 个块；这是历史运行证据，执行新阶段前必须重新检查数量、当前版本及摘要。

本机 Docker 可见 aarch64、10 CPU、约 15.6 GiB 内存；尚未验证模型镜像的 ARM64 依赖安装、推理耗时和峰值内存，不承诺 GPU 加速或全量耗时。当前 Git 工作区在本轮开始时干净。

唯一涉及的 canonical 领域是 platform-operations。既有导入器继续保持不调用 Embedding、不写 Qdrant 的边界；新增独立索引入口，不修改导入语义。分块规范的待同步事项仍属于 prepare-ones-knowledge-chunks，本提案不自动同步其他 change。

## Goals / Non-Goals

**Goals:** 本地离线推理、受限资源占用、版本一致性、可恢复且幂等的双存储写入、真实向量检索及明确的验收边界。

**Non-Goals:** 外部推理服务、GPU/集群调优、采集/定时任务、OCR、混合稀疏召回、Reranker、Web、RBAC、MCP 或通用向量数据库插件层。未来 20 万缺陷的容量评估不能由本轮结果代替。

## Decisions

### 1. 首版选择 BGE-M3 dense embedding，独立 CPU 服务

拟选 `BAAI/bge-m3`、1024 维、float32、L2 归一化、Cosine 距离。通过 Sentence Transformers 的官方模型配置加载，不自行改写 pooling，不加查询指令前缀。模型支持多语言及长输入，但本服务设置更严格的有界输入，不能依赖库默认截断。

使用单独模型服务镜像和小型内部 HTTP 合同：存活/就绪、非敏感模型配置、只读 token 计数、批量文本向量化。客户端调用计数入口预检和组批，不在客户端镜像重复安装 tokenizer/模型依赖。不复用聊天模型连接的请求语义，不将 PyTorch、Transformers 等依赖装入所有业务镜像。不在首版同时支持多个模型后端。

本机先走 Docker CPU，避免引入宿主机常驻服务和 ARM GPU 假设。Ollama 原生/MPS、GPU 内网主机作为后续性能选择，不在本轮同时实现。首版依赖锁、镜像 digest 和模型完整 commit 必须在实现预检时核实并固定；禁止运行时跟随 latest/main。

### 2. 下载阶段与数据处理阶段隔离

独立模型准备命令可下载公开权重，但不能挂载知识数据或数据库 Secret。只取固定 revision 的配置、tokenizer、Sentence Transformers 模块和官方 pytorch_model.bin；不执行仓库远程代码，校验固定文件清单/摘要，写入专用模型卷。用户了解权重格式差异后确认继续：本轮直接使用官方 PyTorch 权重，不增加格式转换或 ONNX 分支。加载必须显式 weights_only=True，不添加任意类 allowlist、不回退不受限 pickle；运行前重新校验权重摘要，采用受支持且已锁定的 PyTorch。这减少而不消除反序列化风险，仍保留隔离/非特权/资源限制。

Embedding 运行时只读挂载该卷，启用 `local_files_only` 和 Hub offline/禁止遥测，`trust_remote_code=False`，缺失文件直接就绪失败，绝不转外部 API。运行服务及 Qdrant 只接入 `internal: true` 的知识网络，无宿主机公开端口。准备任务不接触真实文本，推理任务不接触公网。

索引 CLI 只连接配置中的固定内部服务名，HTTP 客户端禁用环境代理和重定向，不接受命令行任意 URL，也不具备外部 Embedding fallback。真实正文、查询、向量和底层错误响应不写入日志/异常/审计；API 参数校验错误也必须去除输入值。Qdrant 关闭遥测，向量及 payload 同样按敏感派生数据处理。

仅将需要的 PostgreSQL、模型服务、Qdrant、一次性索引/查询容器加入知识网络；Qdrant/Embedding 不加入现有默认网络，知识客户端仅加入知识网络。新增服务使用可选 Compose profile，不改变默认业务栈启动；不要求启动全栈。

用户于 2026-09-17 确认将四个知识服务、专用网络和卷移入 `knowledge/compose.yml`；根 Compose 不保留知识定义或自动 include。使用 `-f docker-compose.yml -f knowledge/compose.yml` 在同一项目中显式叠加，由扩展文件追加 PostgreSQL 的知识网络，保留原网络和数据卷。所有相对构建路径仍以根 Compose 为基准，不能从 knowledge 目录单独启动或另取项目名。保留模型/Qdrant 卷键名，不重新下载已有模型、不重建正式卷。

YAML 锚点不跨文件引用：运维容器明确列出三个已有发布构建参数，并通过测试与主文件保持一致；数据库连接要求现有 `DATABASE_DSN` 非空，不在新文件复制数据库凭据或挂载平台 Secret。该值必须指向同一 Compose PostgreSQL 的内部地址，不能用宿主机 localhost。迁移仍属于共享 catalog；不启用知识容器的环境升级后端时也必须满足该版本的 schema head。本次拆分只变更配置和文档，不执行运行态切换、迁移或全量索引；仍运行知识容器的环境后续运维应持续叠加两个文件，不能用仅主文件的 `--remove-orphans` 或全项目 `down -v` 清理它们。

### 3. 有界推理且不截断证据

初始服务单进程、推理并发 1、CPU 线程 4、Docker 上限 4 CPU/8 GiB；Qdrant 初始上限 2 CPU/2 GiB。先测基准再确认可运行，不把配置上限当作实测消耗。

请求上限 8 条、总计 8,192 tokens、每条 4,096 tokens（含特殊 token）、请求体 256 KiB；使用固定 tokenizer 在推理前准确计数。超限返回固定错误码，不静默截断，不把 1,800 字符当 token 数。客户端按真实 token 预算组成小批次，查询最大 2,000 字符且同样经过 token 限制。输出必须数量/顺序一致、1024 维、数值有限且非零，模型指纹必须匹配。

满载拒绝或限量等待，禁止无界请求队列。对超时/暂时不可用只做至多 3 次有退避的尝试，4xx/配置不一致/内容超限不自动重试。网络操作不放在 PostgreSQL Unit of Work 事务中。

### 4. 用两个小表记录索引及恢复进度

在现有 `knowledge` schema 新增，不新建数据库，也不在 PostgreSQL 重复保存向量：

| 表 | 主要字段/约束 |
| --- | --- |
| `vector_index` | id、显式 code、knowledge_base_id、profile JSON/hash、chunk_profile_hash、corpus_hash、collection_name、expected_document_count、expected_chunk_count、state、固定错误码及时间；code/collection 唯一，绑定知识库 |
| `vector_index_item` | index_id、chunk_id、point_id、embedding_text_hash、state、attempt_count、固定错误码及时间；(index_id,chunk_id) 唯一，point_id 在同索引唯一，chunk 外键 |

profile 完整记录模型 ID/commit、tokenizer/运行配置摘要、维数、dtype、pooling 来源、归一化、距离和空查询前缀。模型、分块配置、语料集合变化时创建新的 index code/collection，不在旧索引混写向量空间。

索引状态 BUILDING/READY/FAILED；逐块状态 PENDING/INDEXED/FAILED。不增加通用任务表、租约调度、插件注册、向量副本或 MQ。单个显式 CLI 是当前唯一写者，同一索引用 session advisory lock 排他；不会在 HTTP 推理期间持有行级事务锁。

先确定当前有效收录和唯一 chunk profile，按主键分页构造固定输入清单，绑定当前 document_revision、块及 embedding_text_hash。清单总数/摘要核验完成后才开始推理；构造中断的 BUILDING 清单可补齐，不能提前标记 READY。输入变化不静默扩充同一索引，须明确建立新版本。

### 5. Qdrant 只存向量和最小定位信息

一个索引版本对应一个显式拥有的 collection。每个 chunk 的 point ID 由 index_id + chunk_id 确定，payload 仅保存 index_id、knowledge_base_id、document_id、document_revision_id、chunk_id、chunk_kind、文本摘要和 profile 摘要；不保存正文、标题、图片 URL、人员或凭据。

创建 collection 时核对 1024 维及 Cosine。只为实际过滤的 index_id、knowledge_base_id 建 payload 索引，并在写入点前完成。相同名称若配置或所有权不匹配即拒绝；不清空、不覆盖其他 collection。首版不启用量化、分片调优或向量别名切换。

Qdrant 默认无鉴权的事实不能忽略：本轮限定独立 internal 网络且不发布端口，只有本机受控 CLI 可达；这不是多租户授权。以后开放局域网或 Web/MCP 必须另行建立认证、TLS/授权边界，不能仅修改 ports。

### 6. 双存储用稳定 ID 和核验恢复，不假装分布式事务

流程：读待处理项 → 本地 Embedding → 校验结果 → Qdrant upsert(wait=true) → 确认完成 → 小事务记录 INDEXED。Qdrant 的写确认不等于 PostgreSQL 状态已成功。

在 upsert 后、记录前中断时，重跑按稳定 point ID 查询现有点，核对 payload 的索引/块/文本/profile 身份及向量维数/有限性，匹配则补记；不存在则重新生成并 upsert。INDEXED 项也要分批核对，不能只相信数据库检查点。检查点成功但点丢失则补写，其他身份冲突停止，不自动覆盖。

处理完成逐项核对全部预期 ID，检查集合 exact count 与预期一致、当前来源版本/收录/文本摘要没有变化，才标记 READY；不凭总数相等推断集合正确。重跑完整索引不得新增点。新语料建立新索引，旧集合不自动删除，清理留待显式批准。

### 7. 检索先做受限运维 CLI，保留后续 MCP 接入边界

查询由 stdin 输入，不放命令行历史或日志；指定 READY 的 index code 和知识库，使用该索引的同一模型/配置处理查询。默认 top_k=10，上限 20；分批扩大候选，最多检查 200 个点，在去重和过滤不足时返回 `partial=true` 及安全原因，不伪称没有更多结果。

Qdrant 候选必须回 PostgreSQL 核对：确实属于该索引和知识库、对应当前文档版本、文档 active、收录 included、块文本/profile 摘要匹配。状态发生变化的旧向量不返回；按文档去重，用最高块分数排序、相同分数用稳定 ID 排序，保留至多 3 个证据块引用。分数是相似度，不是置信度。

CLI 输出引用、分数、定位和质量标记，不向模型会话或日志打印真实正文。此入口属于本机运维验收，不对 Agent 或普通用户开放，不改变 knowledge_base 的 storage_only 或来源 offline_unverified。将来 MCP 的业务授权仍需独立设计，不能复用“本机能连上数据库”作为许可。

### 8. 先基准，再全量；区分链路和业务效果

先用合成数据验收服务与安全/失败路径，再从实际块按长度分层选择 100 个，仅在本地执行基准，记录 token 分布、吞吐、延迟、峰值内存及安全计数；显式预检全部块是否可编码。若超限/OOM/模型不一致，停止全量并报告，不自动换模型、截断正文或接云服务。

全量目标按执行时预检核实，初始预计 8,309 个点。核对数量、point ID 集合、版本、持久性和重放不增量，比较原九表计数/内容摘要，服务重启后验证持久数据。

合成相关/不相关样例及从实际输入重查原块只证明计算和索引链路，不能称为真实 Recall@K。输出与基准只含统计/引用；业务召回质量需用户提供人工标注查询及相关缺陷列表，再测 Recall@10/MRR。首轮无标注时明确记录未验证，不编造“召回率提升”。

## Risks / Trade-offs

- CPU 索引慢或资源不足 → 分层基准、显式限额、断点恢复；必要时再确认内网 GPU 部署，不承诺耗时。
- dense 召回可能漏编号/错误码 → 本轮如实验证 dense 基线，后续用标注结果决定精确词法/混合召回和重排，不提前建设全部算法。
- 本地模型下载仍需要网络 → 下载阶段不持有业务数据；推理阶段断外网。模型来源不可达时支持明确文件清单的离线导入，不调用云端推理替代。
- 两个存储无法原子提交 → 稳定 ID、单写者、逐项核验及 READY 门禁；不通过删除整个 collection“恢复”。
- 索引版本占用磁盘 → 保存原索引以便追溯；重建报告磁盘估算，删除需要单独确认。
- 旧服务镜像与新 schema head 不兼容 → 迁移前核对服务运行状态和新镜像，不擅自停机或启动全栈。

## Migration Plan

1. 用户确认本提案后进入 apply；固定模型 commit、容器 digest 和依赖，验证 ARM64 可构建。
2. 实现纯配置/客户端、隔离模型服务、合成测试与双引擎前向迁移（当前下一号候选 134，执行时重新核对）。相关 tests 纳入 suite tiers，表注释与事实源清单完整。
3. 准备模型文件及本机 Qdrant，只启动必要新服务；验证离线边界/无公开端口及限额，再做 100 块基准。
4. 正式 Migrator 迁移同库 knowledge；CLI 不做 DDL。核对输入及原九表摘要，明确提交全量。
5. 全量核验、重放、恢复、检索 smoke 和安全证据；不归档其他 change，不扩大发布授权。
6. 失败停用本轮索引入口及新服务，保留已有数据库与 Qdrant 卷；不回退账本、不删除原数据。修复后从检查点恢复。

## Open Questions

- 已确认的本轮技术默认：本机 Docker CPU 的 BGE-M3 dense 服务，官方固定 PyTorch 权重受限加载，不增加格式转换或 ONNX 分支。
- 模型依赖在 ARM64 上的可构建性和实测性能是实现门禁，不以文档推测替代。
- 人工相关性标注尚未提供，不阻塞基础索引和安全验收，但真实召回效果必须保持未验证。

## 官方依据

- [BGE-M3 模型卡](https://huggingface.co/BAAI/bge-m3)：1024 维、模型输入上限 8192 tokens、dense 用法及查询无需指令；本服务使用更严格预算。
- [Sentence Transformers 参数](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)：device、revision、local_files_only、trust_remote_code 等加载控制。
- [Hub 文件下载](https://huggingface.co/docs/huggingface_hub/en/guides/download)：固定 revision 和文件选择。
- [Qdrant 安全](https://qdrant.tech/documentation/security/)：默认网络/无认证风险；本轮不发布服务端口。
- [Qdrant upsert](https://api.qdrant.tech/api-reference/points/upsert-points) 与 [payload 索引](https://qdrant.tech/documentation/manage-data/indexing/)：写确认、确定点身份及先建过滤索引。
