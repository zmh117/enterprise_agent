# 知识库部署与使用入口

主平台和全部知识服务统一使用根 `docker-compose.yml`。准备配置、Secret 和持久卷后，在仓库根目录执行：

```sh
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml up -d --build
```

不需要额外 Compose 文件或知识 profile。默认启动六个知识业务服务和 `knowledge-ops-controller`；两个模型准备任务成功退出后，模型服务才启动。一次性 `knowledge-check`、`knowledge-ops` 仍只在 maintenance profile 或显式 `run` 时执行。新安装和旧独立项目迁移见[安装与操作](OPERATIONS.md)。

网页“工具资源 → 知识库”与 `knowledge.sh` 共用持久任务队列。单独管理知识服务：

```sh
./knowledge.sh build
./knowledge.sh up
./knowledge.sh status
./knowledge.sh logs
./knowledge.sh stop
```

构建不会替换运行容器；`up` 应用已构建镜像。任务返回 ID，用页面或 `logs --operation-id TASK_ID` 查看结果。执行器固定使用主项目、主文件及知识服务名单；知识启停不重建 API、数据库或执行器，不删除模型、向量或同步断点。

## 六个常驻服务与三个知识库

| 页面名称 | 服务 | 用途 |
| --- | --- | --- |
| 向量存储 | `knowledge-qdrant` | 保存各知识库的向量集合 |
| 后台模型 | `knowledge-embedding` | 对新增或变化文档编码向量 |
| 检索向量模型 | `knowledge-embedding-online` | 将用户查询编码为向量；本地服务，不是云端聊天模型 |
| 重排模型 | `knowledge-reranker` | 对召回文档进行相关性排序 |
| 检索服务 | `knowledge-mcp` | 执行知识工具、权限复核和检索 |
| 同步进程 | `knowledge-sync` | 一个常驻调度器串行执行计划及其单次同步子进程 |

缺陷、需求、工单共用上述服务，每库保持各自收录关系和固定 collection。一条计划按类型分流到三库，需求子任务进入需求库。新增三个缺陷时只处理对应文档，未变更的需求和工单不重新分块、编码或写向量。

首次采集从 `first_date` 按北京时间创建日扫描到执行当天；之后每小时复查最近七个创建日。时间戳相同但语义内容变化时采用本次采集内容创建本地修订，旧修订保留。较早创建的事项更新需要明确日期补采。普通重启复用模型、向量与持久断点；模型、分块配置或 CPU 架构变化才进入显式索引维护流程。

知识资源发布表示该库配置可用于检索，普通内容更新不重新发布。工具接口升级则需要新的 Agent/应用发布；例如 `knowledge_search` v4 的 hash 不匹配会阻止新 Job。检索实现使用最多 360 秒预算和文档重排；平台知识库授权与离线快照规则见[治理说明](../docs/runbooks/knowledge-governance.md#实现与主规格差异)。

## 文档导航

| 操作 | 文档 |
| --- | --- |
| 安装、启停、计划字段、进度与错误排查 | [网页运维](OPERATIONS.md) |
| 首次采集配置、ONES 凭据与范围 | [全量采集](../docs/runbooks/knowledge-ones-full-collector.md) |
| 增量转换、日期补采、恢复与内容冲突 | [同步与恢复](../docs/runbooks/knowledge-ones-hourly-sync.md) |
| 资源验证发布、双重授权、工具合同 | [知识治理](../docs/runbooks/knowledge-governance.md) |
| 显式建立索引、跨架构与 Qdrant 维护 | [本地向量索引](../docs/runbooks/knowledge-local-vector-index.md) |
| 重排模型、效果评测与升级 | [检索评测](../docs/runbooks/knowledge-retrieval-evaluation.md) |
| 历史离线输入和分块 CLI | [离线导入](../docs/operations/knowledge-offline-import.md)、[文本分块](../docs/operations/knowledge-text-chunking.md) |

## 一次性维护与网络

所有维护命令也只使用主文件，例如：

```sh
docker compose -f docker-compose.yml run --rm --no-deps knowledge-check ready
docker compose -f docker-compose.yml run --rm --no-deps knowledge-ops python -m app.cli.index_knowledge --help
```

模型服务只连接内部 `knowledge-managed` 网络，模型卷只读，运行时禁止下载。准备任务使用固定模型校验和外联网络。API 与 ONES MCP 接入内容网络；Knowledge MCP 只挂载公开 JWKS 与自己的 bootstrap，不持有平台签名私钥、Master Key 或 ONES 凭据。

Qdrant 默认仅发布 `127.0.0.1:6333`。确需可信局域网访问时显式设置 `KNOWLEDGE_QDRANT_BIND` 并限制来源；直连 Qdrant 不经过平台用户授权。内部服务继续使用 `http://knowledge-qdrant:6333`。

## Web 配置独立内容存储

内容连接拆分由 migration **140** 引入；部署使用当前完整 migration catalog 和匹配的 API、ONES MCP、Knowledge MCP、Web。部署与工具验收分别核对，不能以容器健康代替。

页面 TLS 选择必须匹配目标服务器，不因允许管理员账号而自动降级。

1. 准备已经导入、分块并构建 READY 索引的 PostgreSQL 内容库与匹配 Qdrant。首版内容 schema 固定 `knowledge`，不自动建库、搬迁数据或重编码。独立内容库不需要平台 public 中的用户、角色、Job、凭据和审计表，也不要求平台迁移账本；需要与当前内容仓储兼容的表/列。运维迁移内容是另一次显式操作。
2. 选择具备必要读取权限的内容账号：允许管理员、所有者、读写或只读账号，不因具备写入/管理权限而拒绝。至少需要 `CONNECT`、`knowledge` 的 `USAGE` 和内容表必要的 `SELECT`。所需表为 `source`、`knowledge_base`、`knowledge_base_document`、`document`、`document_chunk_set`、`document_chunk`、`vector_index`、`vector_index_item`。当前目录、验证与检索连接仍固定并校验只读事务，保留 5 秒 SQL/连接及 3 秒锁等待上限，不修改账号权限或开放内容编辑。专用低权限账号仍可减小凭据泄露影响，但不是连接准入条件；Knowledge MCP 的平台治理连接默认复用主平台连接；专用最小权限角色是可选运维方式。这些单阶段上限不等于端到端检索时延保证。
3. 在平台“凭据中心”创建数据库密码、可选 Qdrant API Key；不要把密码写进 URL、资源名称、命令或文档。知识资源页面只选择引用，凭据中心可查看知识资源版本依赖。推荐专用只读 Qdrant Key；服务只走检索/校验所需读操作，但 Key 的实际权限仍由目标 Qdrant 配置。
4. 在“工具资源 → 知识库 → 新建/详情”选择“为此知识库配置连接”。填写 PostgreSQL 主机、端口、数据库、用户名、密码引用与 TLS；Qdrant 填写 `http(s)://主机:端口` 和可选 Key 引用。地址按服务所在网络解析，容器内 `localhost` 不是宿主机；证书校验模式依赖服务镜像内受信 CA。TLS 必须匹配服务端能力，不自动降级；本机未启用 TLS 的受信内网连接须显式选择“不加密”。只更换 Qdrant 时可保留“当前平台实例的 knowledge schema”。
5. 点击“读取内容库与索引目录”，选择 KB 与 READY 索引，保存草稿、验证、显式发布。连接变化会使页面旧目录和新草稿验证失效；未发布草稿不影响旧发布。目标索引必须与所选内容库兼容，连接失败不会偷偷使用平台库或旧向量端点。

“验证草稿”仅检查 PostgreSQL、Embedding 与 Qdrant 连接和所选索引配置，最多 30 秒、不自动重试；验证/发布不扫描成员或分块、不重算全库 hash、不统计向量点数。超时返回中文错误，旧发布保持不变。连接通过不代表最新内容已全部同步；后台分块/索引完整性与运行时双权限校验仍独立执行。

平台持有逻辑 KB、角色应用授权、资源版本和审计；内容实例不成为授权事实源。新外部 KB 首次注册仅在平台创建相同 KB ID 的逻辑身份，不复制正文。保持 KB/文档/分块/索引/点 ID 稳定；同一逻辑 KB 不应指向不相关的新语料。

Knowledge MCP 的 `DATABASE_DSN` **复用部署环境中的平台连接**，不能换成 Web 配置的内容库 DSN。内容凭据经固定 `/api/internal/knowledge/storage-connection` 由服务身份＋当前 Knowledge JWT 双重验证获取；仅可读取当前获授权 KB 的已发布连接，不接收任意 Secret 引用。主密钥、签名私钥和 ONES 凭据不进入 Knowledge MCP。离线检索不检查本人 ONES 权限；返回前继续检查当前平台 KB 授权、发布资源、收录及修订一致性。

升级 schema 后，部署账号需具备当前平台授权、知识元数据和审计查询所需权限。默认复用平台连接，无需额外创建知识账号；保留的独立账号配置 CLI 仅供自行选择角色隔离的运维使用。API 与 Knowledge MCP 同步更新后重新兑换短期服务 Token，新 scope 精确包含可读性检查、内容连接和在途 Principal 续期三个内部操作。旧资源字段为空时继续使用原部署连接与原 hash，不要求重发布；切换内容连接才需创建新草稿。原导入/分块/索引 CLI 仍使用它自身的显式部署连接，不会自动跟随 Web 的读取配置。


## 文档重排与 v4 内容合同

在线检索现在需要独立重排服务及 `knowledge-reranker-models` 模型卷。主 Compose 自动等待 `knowledge-reranker-prepare`；网页 `up` 任务同样调用模型准备，不能只准备 Embedding 模型；该操作不会自动发布工具合同或改动索引。按用户的效果优先要求保留 BGE-v2-m3 和长文本，资源配置为 8 核 / 3 GiB，实际质量和时延需在目标环境验证。

准备命令、同候选对照评测、v4 schema hash 协调发布、新 Publication/Job 和回退步骤见[检索评测与运行说明](../docs/runbooks/knowledge-retrieval-evaluation.md)。`retrieval_score` 仅为召回排序分，Agent 应按最终 `rank` 核实详情，禁止自行用数值阈值丢弃尾部。

## 在线与离线内容检索配置

主 Compose 读取 `KNOWLEDGE_ACCESS_MODE`，默认 `online`。在部署 `.env` 中配置：

```dotenv
# 真实环境：默认值，逐项核验本人 ONES 当前可读性
KNOWLEDGE_ACCESS_MODE=online
# 本机离线测试时显式改为 offline
```

`online` 需要可达的真实 ONES、本人有效身份，以及 Agent/应用已选择并授予本人的 `ones_get_work_item_detail` 能力；明确 403/404 项过滤，其他核验失败整次报错，不自动降级。`offline` 只按当前用户和业务应用知识库权限读取入库内容，不要求 ONES 身份、详情工具或服务；本次本机测试采用此模式。非法值阻止启动，模型不能通过参数改模式。

修改模式前等待当前任务完成，再执行 `docker compose -f docker-compose.yml up -d --no-deps knowledge-mcp`。该配置在容器启动时生效；两种模式使用同一工具合同，切换模式无需重建索引或再次发布。目录仍需先发现明确 KB，再调用搜索。结果返回完整标题、状态、来源、来源更新时间、入库时间和至多三个命中文本片段；固定标记为入库快照及局部片段，不代表完整文档或最新来源状态。

目录与搜索输入合同标记已升级，须正式更新 Agent 与应用发布后使用新 Job；保留原数据与知识库范围。首次返回只证明该请求成功，不证明业务问题根因或全库检索完整性。
