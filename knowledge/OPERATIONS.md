# 知识库网页运维安装与操作

适用：同一服务器，主程序与知识服务分开 Compose 管理。管理页面位于“工具资源 → 知识库”。三个 ONES 类型知识库共用服务和一条采集计划，按文档增量更新；发布只控制检索可用性。

## 责任与文件

| 文件/服务 | 责任 |
| --- | --- |
| 根 Compose + `knowledge/ops.compose.yml` | 主程序、数据库、迁移及常驻 `knowledge-ops-controller` |
| `knowledge/deployment.compose.yml` | 独立知识项目，只有知识服务及一次性模型准备/预检 |
| `knowledge/deployment.env.example` | 独立项目的配置模板；不含真实凭据 |
| `knowledge.sh` | 在已安装控制器中提交任务，与 Web 共用状态、互斥和事件 |
| `knowledge-sync` | 一个调度进程串行运行计划，使用现有 `sync_ones_knowledge --mode once` 子进程 |

执行器是高权限组件：只有它挂载 Docker socket，项目和 Compose 文件固定，网页不能传命令、文件路径或镜像。把 socket 标为只读也不能限制其 Docker API 权限。部署源码必须来自可信发布目录；构建期间不要原地改动源码。部署目录、配置及 Secret 文件不可由普通 Web 用户写入。

## 首次安装

1. 按主程序正常发布流程部署匹配的后端、前端及当前 schema head（需包含 migration **152**）。知识入口只检查数据库版本，不擅自运行主程序迁移。
2. 从 `deployment.env.example` 准备权限为 `0600` 的独立环境文件。`KNOWLEDGE_DATABASE_DSN` 指向与主平台相同的数据库；不要输出解析后的 Compose 配置或把实际配置提交 Git。
3. 明确填入已有的三个卷名：Qdrant、Embedding 模型、Reranker 模型。它们在独立 Compose 中都是 `external: true`，缺失会失败，不自动创建空库。仅首次空部署才显式创建相应命名卷。
4. 为主项目提供下面的非敏感安装参数，同时沿用原主程序数据库及 Secret 配置。所有路径必须为宿主机绝对路径；控制器将 Secret 文件映射到相同路径，以便 Compose 正确绑定文件。

```dotenv
# 示例路径，按现场部署填写；不含 Secret 内容。
KNOWLEDGE_DEPLOY_ROOT=/opt/enterprise-agent
KNOWLEDGE_DEPLOY_ENV_FILE=/etc/enterprise-agent/knowledge.env
KNOWLEDGE_COMPOSE_PROJECT=enterprise-knowledge
KNOWLEDGE_STATE_VOLUME=enterprise_agent_knowledge_ops_state
KNOWLEDGE_CONTENT_NETWORK=enterprise_agent_knowledge_managed
APP_CONFIG_MASTER_KEY_FILE=/etc/enterprise-agent/app-config-master-key
PRINCIPAL_JWKS_FILE=/etc/enterprise-agent/principal-jwks.json
KNOWLEDGE_BOOTSTRAP_TOKEN_FILE=/etc/enterprise-agent/knowledge-bootstrap-token
```

独立环境文件中的 `KNOWLEDGE_STATE_VOLUME`、`KNOWLEDGE_CONTENT_NETWORK` 和 Secret 路径必须与主项目一致。`KNOWLEDGE_CONTROL_NETWORK` 必须指向主程序当前 `agent-runtime-control` 的真实 Docker 网络名。控制器扩展会创建共享知识内容网络并把主 API/PostgreSQL 接入；原有控制网络继续由主项目管理。

5. 在维护窗口，主项目继续使用原项目名，加载 `knowledge/ops.compose.yml`，构建匹配镜像、运行原迁移流程，更新 API/前端，并启动控制器。例如在所有安装参数已由受控环境提供时：

```sh
docker compose -p enterprise_agent -f docker-compose.yml -f knowledge/ops.compose.yml \
  --profile knowledge-operations config --quiet
docker compose -p enterprise_agent -f docker-compose.yml -f knowledge/ops.compose.yml \
  --profile knowledge-operations build migrator api-server knowledge-ops-controller
# 使用主程序既定迁移、前端发布与启动流程；接入新网络可能重建 PostgreSQL/API。
# 迁移完成且 PostgreSQL/API 已使用上述扩展后，单独启动控制器：
docker compose -p enterprise_agent -f docker-compose.yml -f knowledge/ops.compose.yml \
  --profile knowledge-operations up -d --no-deps knowledge-ops-controller
```

如果安装参数在环境文件中，在上述所有命令中明确增加 `--env-file`，保持与原主程序相同的配置来源。不要使用 `down -v`、`--remove-orphans`，不要用独立知识项目管理主数据库。

升级包含 MCP 工具接口变更时，还要核对当前启用应用及其 Agent 发布版本中的工具 Schema。旧发布版本不自动采用新接口；例如知识检索 v2 会改变 `knowledge_search` 的合同。保留原配置和工具范围，依次创建 Agent 草稿并校验发布、更新应用引用并校验发布、在原环境激活。不得直接改写历史发布记录的 hash 或关闭合同校验。升级后用一条新的渠道消息核对接收、Job 执行和回复投递；容器健康不能替代这项验收。普通内容同步和同接口重启不需要重新发布。

6. 控制器显示在线后，网页依次“构建镜像”“启动 / 应用版本”。首次需要准备模型；已有模型按文件校验复用。三个库共享后台模型，在线 Embedding 仍保持独立进程，Reranker 维持原资源配置。
7. 接入原采集计划，或在网页新建计划，填写 ONES 团队、项目、类型 ID、凭据中心引用及三个知识库编码。保存会关闭采集安全开关，开启自动同步后立即调度首次全量；已有未完成任务优先恢复。已有在线来源配置及运行记录时，来源范围不能原地修改。来源配置只引用凭据，不接受 Token 正文。

## 采集计划字段

一条计划覆盖缺陷、需求、工单三个知识库。Web 新建/配置计划与 `collect_ones_knowledge --mode configure` 使用同一配置校验；示例结构见 [ones-collector.example.json](ones-collector.example.json)。该文件包含项目特定范围，不是所有环境都能直接采用的通用模板，必须确认目标与现有来源一致。

| 字段 | 用途与填写规则 |
| --- | --- |
| 计划编码 | 计划的稳定唯一编号；创建后编辑不更名，用于选择同步、补采和状态 |
| 来源编码 | 来源文档的稳定命名空间；接续同一批历史数据沿用原编码，不混用其他 ONES 团队/实例 |
| ONES 地址 | 根 origin，例如 `https://ones.example.internal`；不包含 API 路径、用户名、查询串或片段 |
| 团队 ID | 实际 ONES Team ID，不填团队名称 |
| 项目 ID | 采集范围中的实际项目 ID，逗号分隔，1–100 个且不重复 |
| 凭据中心引用 | `secret://platform/<code>`，预先在凭据中心配置受管采集身份；保存引用不创建凭据 |
| 首次采集起始日期 | `first_date`，按北京时间根工作项创建日，从此日到首次执行当天，含首尾；不得晚于当天 |
| 缺陷知识库编码 | 缺陷写入的知识内容库 code，不是工具资源的显示名称 |
| 需求知识库编码 | 需求及其子任务写入的知识内容库 code |
| 工单知识库编码 | 工单写入的知识内容库 code；三库 code 必须不同 |
| 缺陷 / 需求 / 工单类型 ID | 各类别实际工作项类型 ID，不是某条单据 ID；每类 1–20 个，逗号分隔 |
| 子任务类型 ID | 校验需求详情中列出的子任务类型，1–20 个；采入需求库，不创建第四个库 |

编码与 ID 只接受 1–128 位英文字母、数字、下划线和短横线；四组类型 ID 不能重复。当前表单要求三库和子任务类型都填写，不支持只配一个库或自动发现类型。补齐历史计划时保留原计划/来源 code、三库映射和 `resource_ids`；不要直接用示例中的空 `resource_ids` 覆盖原资源绑定。

采集凭据的受管值仅包含 `token`、`user_id` 两项，由凭据中心保管，不能填到计划或文档。同步容器需挂载平台 Master Key；目标主机需加入 `ONES_MCP_PROVIDER_ALLOWED_HOSTS`，HTTP 目标还需显式允许。配置能保存不证明凭据存在、目标可达或索引已完成增量转换。

保存后显示“采集未启用”。`enabled` 是采集安全开关，`schedule_enabled` 是定时调度开关；旧计划的后者可能保留，但前者关闭时不会执行任务。点击“开启自动同步”才启用采集并立即调度。暂停自动同步只暂停后续定时触发，当前/排队显式任务继续；资源停用也不等于暂停采集。

## 服务状态与任务进度

- “检索向量模型”是本地查询 Embedding；“后台模型”用于文档向量化；“重排模型”对已召回文档排序。三个知识库共享它们，职责和资源上限见 [部署说明](README.md#六个常驻服务与三个知识库)。
- 服务“运行中 · 就绪”表示容器与就绪检查通过；不证明计划已配置、最近同步成功或用户可检索。
- 操作状态包括排队、运行、等待重试、成功、部分失败、失败和中断。采集/同步另显示当前阶段及按库计数；采集数量不能当作可检索数量，单文档向量计数不能当作整库完成数。
- 构建/服务启动没有可靠总量时显示阶段和事件，不估算百分比。刷新或关闭网页不影响后台任务；执行器或同步心跳过期显示未连接/未知。
- 首次全量完成前不能补采。补采按创建日期，不改变常规七日窗口；一次任务作用于计划下三库，各库只处理自己的变化文档。

## 从旧扩展接管

先核实原主项目、卷和网络名称。已有固定集合和增量身份保持不变；尚未完成增量接管的环境先按原手册执行显式 adoption，不能以新运维入口代替数据合同升级。

在切换前停止旧同步进程及旧知识服务，示例仅列知识服务：

```sh
docker compose -p enterprise_agent -f docker-compose.yml -f knowledge/compose.yml \
  -f knowledge/mcp.compose.yml -f knowledge/sync.compose.yml \
  stop knowledge-sync knowledge-mcp knowledge-embedding-online knowledge-reranker \
  knowledge-embedding knowledge-qdrant
```

不要同时运行旧 daemon、独立 cron 或手动 once 作为新队列的调度器。保留的来源锁可阻止并发写入，但不能用它代替运维接管；旧容器不能与新项目抢占端口或网络别名。确认新配置绑定的是旧卷后，再从 Web 启动新项目。

自定义 PostgreSQL 连接不必然是外部数据库，但需要核实实际目标。真正外部内容库只保持原读取合同，不能因网页新增功能而自动开启写入。不同 CPU 架构的 profile 仍需原有显式索引验证/重建，正常同架构重启不重建全库。

## 日常操作

```sh
./knowledge.sh build
./knowledge.sh up
./knowledge.sh stop
./knowledge.sh status
./knowledge.sh logs
./knowledge.sh sync --binding-code mes-ones
./knowledge.sh backfill 2026-10-10 2026-10-29 --binding-code mes-ones
./knowledge.sh retry --operation-id TASK_ID
```

主项目不是 `enterprise_agent` 时设置 `KNOWLEDGE_MAIN_PROJECT`。只有一个启用计划时补采可省略 `--binding-code`。命令返回持久任务 ID，不等待长任务完成；用页面、`status` 或 `logs --operation-id TASK_ID` 查看进度。`logs --after CURSOR` 可接续读取，返回最近/后续最多 200 条安全事件。

- 构建使用独立任务版本标签，成功后才记录可应用版本，不触发采集或替换运行容器。
- 启动检查 schema、外部卷/网络和服务就绪；应用版本前先停止旧同步。失败显示具体阶段，不宣称启动成功。成功后恢复未完成任务，遵循每条计划原自动调度开关。
- 暂停自动同步不关闭采集安全开关，不打断当前任务，不影响已排队的显式任务或在线检索。
- 停止服务先等待同步保存断点，再停止检索、模型及 Qdrant，保留卷和控制器；主程序继续运行。
- 补采以北京时间**创建日期**为范围，含首尾日期。首次全量完成后才允许补采；等待同来源当前任务完成，恢复时不能改变日期。
- 日常七日窗口不是“全部更新时间”的覆盖保证。较早创建、后来修改的事项需要明确日期补采。
- 列入重试范围的瞬态依赖失败总计最多尝试三次（首次执行加最多两次自动重试）；部分失败或耗尽后在任务记录显式重试，复用原任务、范围、run 和成功文档。其他来源计划仍可调度。
- 控制器中断后先核对状态；已确认停止可完成原任务，构建或启动无法证明完成时标记中断，由管理员重试。不会把失联等同于执行成功。
- 事件包含阶段、计数、稳定错误码及同时间戳修订的安全身份/hash，不提供原始容器终端输出、业务正文或认证材料。

## 常见问题

| 现象 / 错误码 | 核对与处理 |
| --- | --- |
| 未找到唯一运行的知识运维执行器 | 确认主项目控制器在线及 `KNOWLEDGE_MAIN_PROJECT` 正确；`knowledge.sh` 不负责安装控制器 |
| 已保存计划但没有采集 | 确认“采集未启用/自动同步暂停”、凭据引用、目标允许列表及三库增量接管状态 |
| `knowledge_collection_identity_missing` | 凭据不存在、不可解密或受管结构不符；在凭据中心配置，不把 Token 加到计划 |
| `knowledge_sync_migration_required` | 既有索引或活动运行仍为旧模式；按[同步手册](../docs/runbooks/knowledge-ones-hourly-sync.md#已有索引的一次性转换)转换，不删除向量 |
| `knowledge_ops_retry_required` | 来源仍有失败/部分失败任务，重试原任务；不要新建计划或扩大日期范围 |
| `knowledge_collection_scope_changed` / `knowledge_collection_range_changed` | 已冻结来源配置或补采日期不同；恢复原参数，来源确实改变时另建计划 |
| `mcp_tool_schema_drift`，消息没创建 Job | 升级后的工具合同与应用发布不一致；正常校验、发布 Agent，再更新发布并激活应用；不需要重建知识索引 |

同时间戳但内容变化在受管在线增量路径直接创建本地修订，保留旧版本及原来源时间戳；离线导入仍可能返回 `knowledge_source_version_conflict`，不能把两条路径的处理混淆。详见[同步日志](../docs/runbooks/knowledge-ones-hourly-sync.md#同时间戳内容变化的处理和日志)。

## 回退与验收边界

回退前停止新项目并停止主项目的控制器，避免新任务再次启动知识服务；保留全部卷及 migration 152。按旧部署流程重新启用旧知识服务，不与新同步进程并行。不要通过删除知识数据回退运维界面。

代码本地验收包括迁移、HTTP 权限、幂等队列、固定日期续跑、假 Compose 启停顺序、真实隔离 PostgreSQL 并发、控制器镜像构建和合成数据浏览器交互。它们不代表现场 ONES、模型下载或已有外部连接已验收；正式接管后需要核对一个实际同步轮次及三库检索。
