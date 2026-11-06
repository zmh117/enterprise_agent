# 状态机候选独立源码核验

日期：2026-11-06。核验者为当前实施 Agent；不采用提取模型自评作为业务通过依据。源码为本地冻结基线，清单 `ca44b57635a5dfad82a964eba80d1307123a97cfc20d2e398d06ec436144a187`，SVN revision 未知。

独立问题集为 `mes-independent-review-cases.json`，原文件摘要 `8372bac5394f9d8a224e8dc8aa9cab5c4b2b4fea6774f8d623455d68a50a1584`。保留原始预期，不将预期答案交给提取模型。新增调用链发现单独记录，不能只检查关键词命中。

## 第一轮 v2：不通过业务核验

构建 `13b0b556-ab97-5e8e-949f-39a10d23a532`，快照 `edef30fb-b6e2-5b56-94d9-2624a84d9c7d`。真实模型 `deepseek-v4-flash` 通过已发布 Runtime 配置读取源码，封装候选并写入 PostgreSQL 状态机关系表。结构通过不等于以下语义通过，未审批或激活。

| 入口 | 独立发现 | 判定 |
| --- | --- | --- |
| 工单发布 | 有效期提示的正常早返回未独立建 unchanged 迁移；完整成功目标仍混入该路径。补偿成功与补偿失败合并，结构化失败目标声称 140，描述又承认补偿失败未知。处方运行期物料复制、循环内 Update 失败继续的规则未覆盖。部分外层非零 ID 条件丢失。 | 不通过 |
| 工单报工 | 正确区分准备和确认，但确认后不改变工单状态、库位提示后返回成功的路径只存为 rule，没有迁移。多个可读公共函数未继续读取；17500 由前端解释推断异步，未核验错误码定义。 | 不通过 |
| 工单开始 | 请求受理迁移明确，但后台执行目标直接标为生产中；未追踪 WfRun、工作流事件和状态回调，不能证明该调用返回时主记录已落库。 | 不通过 |
| 集团授权 | 关键调用已记录，但未读可访问的 GroupAppAuthorize::Update；把调用参数 opt_user 当成该表的写入字段。多条无额外守卫的说明使用 unknown guard。前后端请求字段差异的 summary 直接推断丢失关系，超出路由和转换已知证据。 | 不通过 |

机器表已有对象、机器、状态、事件、迁移起点及失败分支真实记录；它们仅是候选。保留失败候选及 Job 审计作为质量证据，不改写原产物或用人工编辑冒充原模型输出。

## 新增调用链发现

1. `set_server/mes_core_mod/MDWorkflowRun/src/WorkflowEngine/WorkflowEngine.cpp:103` 的 AddWorkflowInsRun 在找不到批次、已有工作流时正常返回；`974` 的 WfRun 委托该函数。`Workflow.cpp:11` 的 Run、`499` 的 SetStatus 再产生事件，`WorkflowEngine.cpp:382` 的事件循环调用回调。
2. `set_server/mes_business/MDWORun/src/Logic/WOKernel.cpp:28` 的 onWOStatusChanged 仅对顶层工作流调用 UpdateStatusByWO。`MDEBRCache/src/CachedWorkOrder.cpp:324` 先读/写 Redis，再更新生产工单表；手动暂停状态可忽略工作流更新，缓存与数据库失败可能分叉。状态历史、通知、缓存和主记录不可混为同一成功边界。
3. 报工依赖的 CachedMat、WMSDataHelper 和 SafeDBTransaction 均在已准入源码中；已加入导航。`set_server/include/ErrorDefine.h:889` 定义 17500 为向其他系统发送失败，不能据前端提示将其等同于异步受理。
4. CustomCheck.cpp、GroupingGroup.cpp 和个别协议头文件被来源准入记录为 sensitive_content，保持排除。调用点已证明的检查条件可表达；内部算法未覆盖，不能扩写为完整权限政策。

## 原始预期的源码澄清

G01/G02 的“写 status 和 opt_user”来自 GroupingApplication.cpp 的调用参数。进一步独立读取 `set_server/mes_business/MDComponents/DatabaseComponent/GroupAppAuthorize.cpp:27` 后确认：SQL 设置 status（以及实际传入的其他支持字段），opt_user 被传给同步记录 AddSyncInfo，不能说主表 SQL 同时写入 opt_user。原问题集不修改，后续验收按完整调用链核验此澄清。若同步记录失败，主表写入是否保留还须结合调用方事务边界说明。

第一轮发现用于修正一般提取规则、目录和源码导航，不把逐题答案填进下一轮候选。

## 第二轮 v2 与直接审校

第二轮发布单元结构校验通过，但仍漏掉运行期物料计划回填，条件规则没有完整保留外层非零 ID，已有工单的成功 guard 只概括 ID/状态，缺少与保存并发布前置检查的连接；把组态20和运行期10/20混成一个生命周期。仍不审批。

2026-11-06 用户要求停止额外模型 API，改由当前 Agent 总结源码并入库。原构建因 `code_manual_review_requested` 终止，剩余报工 Job 在 05:13:12 UTC 确认停止执行。之后新增审校包，不改写原模型产物，不声称是又一次真实模型提取成功。当前 Agent 编写和复核不能声称为另一位独立审核人，逐题核对只是源码审校材料，未通过全量业务审批。已入库结果和覆盖范围见 `source-review-20261106.md`。
