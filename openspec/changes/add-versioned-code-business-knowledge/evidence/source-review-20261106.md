# 当前 Agent 源码审校入库

2026-11-06，按用户“暂时不要用api了，你来总结业务写入数据库”执行。当前 Agent 直接阅读冻结源码并编写知识包，没有新增 Runtime 模型任务或调用 Embedding。原模型候选保留为失败证据，审校内容不冒充原模型输出。

## 已保存的实际数据

- 来源快照：`dfb1ef9f-4365-51e4-9e41-2780bfb2b640`，清单摘要 `ca44b57635a5dfad82a964eba80d1307123a97cfc20d2e398d06ec436144a187`。本地基线，SVN revision 未知。
- 审校构建：`7fd383a6-2f66-5f2c-b2ce-aedccd188a23`。
- 知识快照：`0ad7a672-308b-531e-81cf-d3ec48aa5d9f`，`CANDIDATE`，构建等待 `VALIDATING`，`origin_kind=source_review`。
- 13 个统一对象、3 个状态机、11 个状态、10 个目录事件、12 条迁移、31 个失败分支、19 条规则。
- 44 个快照成员 = 31 条人工编写业务知识 + 13 个控制器身份节点。
- 46 条关系 = 15 条有源码依据的业务关系 + 31 条控制器对象 contains 关系。
- 46 处证据，逐项绑定文件 ID、路径、符号、行号、原始/表示摘要、段落摘要。

工单发布、开始、报工都引用 `factory.work_order`。工单组态为 `factory.work_order.configuration`（WO_INFO.C_STATUS），运行期为 `factory.work_order.execution`（WO_PRODUCTION.C_STATE）。集团应用为 `group.application.lifecycle`。`source_mode=any` 明确表示所选物理状态字段没有旧值门槛，并仍受 guard 限制；不是漏填，也不是“任意输入都允许”。例如后台启停方法没有前端按钮相同的旧状态检查，不捏造后端限制。

迁移包括：发布前有效期提示不变、组态发布20、非称量后台运行期发布20、开始请求受理不变、工作流40回调落库、报工准备不变、库位冲突提示不变、结束/终止报工转60、其他报工只增次数、集团启用2、停用3和授权替换但生命周期不变。

## 原问题集逐项源码复核

以下是编写者对已入库规则的逐项源码核对，不是独立人员验收，也不是模型在线问答评分。业务 key 均在上述知识快照中。

| 问题 | 已核验结论 | 主要业务 key 后缀 |
| --- | --- | --- |
| P01–P02 | 正式工单开关默认 false，只放宽非零处方为非作废；主配方仍须发布，有效期仍检查，`#if 0` 不生效 | publish.related_object_guards |
| P03 | 模拟分支保留非零 ID 外层条件、未过期和非作废/废弃条件 | publish.related_object_guards |
| P04 | 允许计算状态10/12/140；组合读取不等于单独组态字段，组态20还会读运行状态 | publish.effective_state、configuration_commit |
| P05 | 两个 ID 都非零才检查关联；局部跳过不证明全流程允许缺失 | publish.pi_formula_relationship |
| P06 | 提示早返回是独立 unchanged 迁移；继续不跳过全部检查 | publish.expiry_prompt、save_publish_prechecks |
| P07 | 处方明细复制为运行期，计划回填按工单/版本/处方/步次/剂次/顺序定位；用量属于明细 | publish.material_snapshot、planned_material_override |
| P08 | 物料回填失败只记录；组态补偿成功与失败分开，跨阶段没有整体事务 | publish.configuration_commit、planned_material_override |
| S01 | 请求校验后入线程池立即回执，不代表40已写 | start.request_accepted |
| S02–S03 | 后台20/30及参数门槛；入口权限/签名调用条件，不推断内部完整策略 | start.execute_checks、request_accepted |
| S04 | 后台历史、Redis、列表通知与实际工作流状态回调分别表达 | start.workflow_success_boundary、working_state_callback |
| S05 | 批记录头/PI文本请求失败记录后继续，不必然阻止WfRun | start.execute_checks |
| R01 | EBR报工页面先准备/签名再确认；mat_decl_ack与reportrun查询不同 | report.frontend_chain |
| R02–R03 | AND保留先行配置门槛，不能用后面的生产中报工分支绕过 | report.prepare |
| R04 | 准备入口旧状态更新已注释；实际状态调整在本地提交和同步检查后 | report.prepare、confirmed_finished |
| R05 | ERP/LIMS错误发生在本地提交之后；不同返回码及保留动作单独保存 | report.confirmed_finished、confirmed_other |
| R06 | 当前50/100转60，其他只加报工次数，两个互斥迁移 | report.confirmed_finished、confirmed_other |
| R07 | 运行期处方产出 + 当时MAT_HEADER关联查询，不能概括成全快照或全实时 | report.inputs_and_current_material |
| G01–G02 | 启用2、停用3；按完整调用链澄清opt_user是同步操作人，不是本次主表SQL字段；不清空scope或删除应用 | enable.status_write、disable.status_write |
| G03–G04 | 授权校验、更新scope、删除旧关系、逐项插入及事务归属；方法差异不能推断整个启停接口无认证 | authorization.replace_scope、authorization_method_difference |
| G05 | 两处页面字段和签名处理不同；Parse读data_array，保留路由/转换与现场影响未知 | authorization.frontend_payload_difference |

原始 25 题文件保持原摘要不变；G01/G02 的原预期措辞澄清见独立核验文档。本次还记录了 WfRun 无batch/已存在实例也返回成功、Redis先写而数据库失败、报工库位提示成功但未提交、GroupSyncInfo无目标也可能返回成功等边界。

## 验证与未完成范围

管理员 CLI 在验证源码、原失败构建摘要、同来源 Job/Invocation 停止及当前权限后，以单一事务保存不可变修订及状态机投影。原构建摘要为 `cbddc6154206b984049e22eed55345331e95f474add1d24e48e4f051cdc79471`。来源/证据/状态引用不匹配回滚；重复输入返回同一构建/快照。

实际 PostgreSQL 逐条回读：31 条业务记录与输入一致，12 条迁移的关系投影与不可变修订一致，管理详情五页44条完整返回。错误知识库与未就绪快照不能作为公开知识读取。其他来源文档15,778、修订17,654，数量未变。当前来源没有运行中模型 Job，定时采集和按需历史构建均关闭。

最新后端相关测试133项通过；新增导入原子性、幂等、权限、摘要/证据拒绝，以及同对象不同状态维度和事件归属测试均通过。核心mypy及Ruff通过，构建与健康检查通过。实际导入复用 job-dispatch-worker 已有只读源码挂载；首次在无源码挂载的 API 容器尝试时在校验前停止、未写数据库，没有给 API 容器新增源码权限。

前端候选状态机展示4项测试通过，OpenSpec严格校验和diff空白检查通过。本次只读SQL四条在实际PostgreSQL分别返回12条迁移、31条失败、46条关系、19条规则。实际重复导入返回`created=false`且构建/快照ID相同。

**当前并未启用问答。** `machine_valid=true`，`business_verified=false`，`activation_blocked=true`，`active_snapshot_id=null`。发布和报工入口覆盖标为 partial：称量服务器完整生命周期、所有嵌套保存/编译/仓储政策、公共权限/签名内部策略及现场配置未穷尽。知识只回答已经取证的路径和边界，不能据此判定任意现场输入必然允许操作。本次不触发Qdrant索引、Embedding、完整MCP问答或真实SVN版本对比；这些原验收项保持未完成。

本地可复核材料（不包含凭据或源码全文）：

- `.local/code-knowledge/acceptance/source-review-20261106/author.py`：当前Agent直接编写的摘要及证据定位，生成器仅装配/校验，不调用模型。
- 同目录 `authoring.json`、`validation.json`、`import-result.json`、`import-replay.json`、`db-verification.json`。
- `state-machine-v2-inspection.sql`：只读查询所有MES候选和当前启用指针；`source-review-20261106.sql`只查本次审校快照。
