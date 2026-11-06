# 状态机 v2 实现与本地部署证据

日期：2026-11-06。本文是实现/运行证据，不替代 canonical spec，也不等于真实 MES 业务验收。

## 已实现结构

提取合同升级为 `code-business/v2`。模型只提交 transition/rule；系统统一生成目录对象身份。工单各操作使用 `factory.work_order`，机器为 `factory.work_order.lifecycle`；集团应用使用 `group.application` 和对应 lifecycle。目录及摘要进入提取配置，状态身份在同快照各单元之间复用。

迁移明确记录 `from_state`、`event_key`、`guard`、按序 `actions`、`to_state`、`failures` 和成功边界。失败分支包括条件、发生阶段、结果类别、失败后状态、已经保留的动作及证据。`unchanged` 与 `unknown` 分离；请求受理不能直接充当后台完成迁移。条件表达式只作为数据，不执行。156 迁移增加仅用于已取证失败分支的 `indeterminate`：必须列出现场核验字段，不能用于成功目标或替代缺失分析。

迁移 155 新增以下 PostgreSQL / SQLite 等价表，与不可变知识修订同事务保存：

| 表 | 实际职责 |
|---|---|
| `knowledge.code_object` | 快照内统一对象身份和知识节点 |
| `knowledge.code_machine` | 对象的状态维度 |
| `knowledge.code_state` | 机器内状态标识、源码值、名称和证据 |
| `knowledge.code_event` | 对象允许引用的事件身份 |
| `knowledge.code_transition` | 事件、条件、动作、起点/目标描述及成功边界 |
| `knowledge.code_transition_source` | 每条迁移的明确起始状态集合 |
| `knowledge.code_transition_failure` | 每条迁移按序的失败条件、剩余状态及保留动作 |

起点、目标和失败状态通过外键约束在所属机器中。相同机器/状态 key 的原始值冲突、一个原始值对应多个 key、跨对象事件引用都会拒绝。详情读取同时核对关系投影与不可变修订，缺失或不一致不返回可用事实。检索投影包含完整迁移，版本比较覆盖目标/失败分支，管理页面显示迁移和失败后状态。

## 验证

- 后端相关、状态机新用例、迁移与事实源：149 passed。
- 独立 PostgreSQL 实例：迁移/读取角色相关 40 项首次通过；2 项旧表/列数量断言更新后复跑通过，共 42 项。另实际执行 v2 写入、关系表查询与详情 roundtrip。
- 独立 Qdrant 实例：1 passed，验证固定快照检索及内容复用。
- 前端候选页面：4 passed，包含起始状态、动作与失败后状态展示；TypeScript 与管理页镜像构建通过。
- 相关 32 个 Python 源文件 mypy 通过；Ruff、diff whitespace、OpenSpec strict 通过。
- 合成测试覆盖身份/机器/事件错误、状态引用、状态值冲突、未知阻断、失败保留动作引用、异步受理、跨单元同对象、事务回滚、投影不一致、版本目标/失败变化、清理范围及 ONES 保留。它们不计作真实 MES 验收。
- 后续修正版相关后端/迁移/事实源 121 passed，前端 4 passed；6 个新增或再次修改的核心文件 mypy 通过，镜像构建通过。已有其他相关测试结果不与这些重叠用例相加。
- 关系读取增加对实际列中目标模式/状态、失败模式/阶段/结果及状态原值的核对；不仅比较 JSON 列。独立 PostgreSQL 读取角色 22 项通过。155→156 在有失败行的独立 PostgreSQL 上迁移，原行内容摘要保持一致；新模式完成实际写入读取 roundtrip。

## 本地部署与旧候选清理

本地 PostgreSQL 已成功从 154 升级至 155，再以前向迁移升级至 156。相关服务与管理页面使用更新镜像；没有运行中的 Job 时执行部署。既有 `knowledge_mcp_reader` 增加三张迁移读取表和状态表的必要列，并通过完整最小权限合同校验；未更换凭据。

按用户授权只清理 MES 来源 `ea3fd4a6-3eac-538b-bf73-b57509593147` 的未激活、未索引、无活动执行 v1 候选：32 个知识标识、36 个修订、36 个快照成员、37 条关系。预检清单摘要：`45dc2e04dc5a53b53d6a35cf0635c94beb219a568b4a73fce03bcb51a423520b`。清理执行重新校验同一摘要。

5 个历史构建、对应 Job/审计及源码快照保留；旧候选快照标记不可用。旧合同不能重试或继续导入。5,550 个源码文件元数据保留。其他来源的 15,778 个文档、17,654 个修订在清理前后数量和身份/内容摘要完全一致：

- 文档摘要：`ccb25ea2fc8a9db43221bcab411ef3c2451ba4adfe0ca3f3a4bc0f69a6fc70ab`
- 修订摘要：`05f21d51e150c8538b40ead843e250bda47d77340566ffd7552241619d8bd534`

## 真实模型与源码核验（模型已停止，审校版已入库）

- 本地源码基线 `dfb1ef9f-4365-51e4-9e41-2780bfb2b640`，清单 `ca44b57635a5dfad82a964eba80d1307123a97cfc20d2e398d06ec436144a187`；SVN revision 未核实。
- v2 构建 `13b0b556-ab97-5e8e-949f-39a10d23a532`，知识快照 `edef30fb-b6e2-5b56-94d9-2624a84d9c7d`。
- 新提取 Agent 发布 `agent_publication_59725e4bdda24208803f660ce2143b56`，应用发布 `business_app_publication_8ebe2c3814a8412da7594555bcd6fd76`。
- 第一轮在独立核验中未通过，已保留候选和审计，构建标记 FAILED；通过标准取消机制停止剩余依赖提取，确认 Invocation 停止后部署。集团启用尚未在第一轮运行。详细缺陷见 `state-machine-v2-independent-review.md`。
- 第二轮构建 `697d606d-d3a6-5c27-a96e-63f47468ac66`，快照 `6c822902-a101-5aa9-847f-a8848103ada2`。Agent 发布 `agent_publication_32d192e8d969447f8e7ac6c7c1553518`，应用发布 `business_app_publication_47378d00154d48ec81f208139a95a748`。冻结目录 `mes-code-identities/v2`。发布单元仍未通过源码核验；按用户“暂时不要用api”指令停止构建及报工 Job，确认 Invocation 已 quiesced。原产物和审计保留，不继续模型调用。
- 独立预期沿用提取前准备的 `mes-independent-review-cases.json`，不提供给提取模型。实际结果另行记录，不修改预期来适应模型输出。

## 当前 Agent 直接审校入库

按真实状态字段将目录升级为 `mes-code-identities/v3`，工单对象仍为一个，组态和运行期为两个机器。数据库结构仍为 156，无修改已应用迁移。新增管理员 CLI 原子导入，由已有只读源码挂载的 job-dispatch-worker 容器执行，不给 API 容器扩大源码访问权限。

审校快照 `0ad7a672-308b-531e-81cf-d3ec48aa5d9f` 实际保存 13 个对象、3 个机器、11 个状态、12 条迁移、31 个失败分支、19 条规则；46 条关系中包括 15 条源码业务关系和 31 条控制器 contains。46 处证据经过固定源码逐行摘要校验。结构和关系回读通过，保留未覆盖关键项，未启用、未索引。详见 `source-review-20261106.md`。

最新相关后端测试 133 passed，4 个新改核心文件 mypy、Ruff 通过。实际 PostgreSQL 导入和五页管理详情回读核对全部 31 条人工编写的业务记录与原包相同，12 条迁移的关系投影与不可变修订相同。非就绪快照和错误知识库访问均拒绝。此结果不替代在线问答、真实 SVN 变更或 MES 生产运行验收。
