## Why

业务用户需要从实际代码中理解业务规则、数据库表字段及提交带来的行为变化，但不能获得真实源码。当前知识能力面向 ONES 工作项，尚无 SVN 代码分析、逐提交同步和业务变化时间轴，需要在现有角色授权与知识基础设施上增加这条来源链路。

## What Changes

- 接入显式配置的 SVN 主干路径；首次固定接入时的提交建立当前基线，不回溯接入前历史，基线构建期间的后续提交连续补齐。
- 新增受限后台代码分析任务，首批覆盖 C++、Vue、Java，从入口、调用链、条件分支、权限校验、状态变化、持久化及异常处理提取业务事实。注释、docstring 和提交说明不作为规则成立的证据。
- 允许业务用户获取表名、字段、类型、约束、关联及有代码依据的业务含义；源码正文、原始 diff、源码附件、凭据和私有证据不进入问答链路。
- 采用 SVN 提交通知与定期补扫，逐条处理范围内提交，保存去重、恢复与连续进度；处理成功后自动更新当前知识和检索索引，不要求逐次人工发布。
- 按稳定业务主题维护当前事实，并追加包含变化前后、影响范围、提交时间与分析时间的业务事件；无行为变化的提交仅记录处理结果，不制造变化事件。
- 在线查询使用现有角色中的应用、Tool 和知识库授权，无需用户 SVN 身份或第二套知识 ACL。新增代码知识目录、当前知识查询和变化时间轴查询工具，保持现有 ONES 工具合同与个人可读性校验。
- 每次当前知识查询以本次查询开始时服务器确认的 SVN 目标为新鲜度要求；未追上时有界等待，超时明确暂不可用，禁止把旧知识或零命中作为降级结果。
- 产品只提供当前知识与时间轴，不提供知识版本列表、选版或回滚；内部提交位置、索引代际及短期读取批次只用于证据、一致性和故障恢复。

## Capabilities

### New Capabilities

无新增 canonical 领域；以下能力均作为现有领域的增量。

### Modified Capabilities

- `platform-operations`：新增 SVN 来源接入、受限代码分析、基线建立、逐提交同步、当前事实与业务事件存储、原子激活、恢复与运行治理；调整知识来源及受管激活要求以明确代码来源分支。
- `builtin-tool-resource`：新增代码知识固定工具、完整业务事实与表字段投影、最新查询等待、连续时间轴和无源码输出边界；限定原有 ONES 双重授权要求的适用来源。
- `identity-access`：明确代码衍生知识复用现有角色知识库范围、当前授权复核及后台 SVN 身份隔离，不引入第二套 ACL。
- `business-application`：新增代码知识工具组合、Publication/Job 合同冻结和知识来源类型匹配，保持 ONES 工具依赖独立。

## Impact

### 当前事实（Confirmed-current，2026-10-16 本地源码核对）

- `backend/app/shared/knowledge_tool_contracts.py` 的两个知识工具返回 ONES 引用，正文依赖 `ones_get_work_item_detail`；不具备代码知识正文合同。
- `backend/app/modules/knowledge/domain/tool_policy.py`、`infrastructure/job_access.py` 与 `services/knowledge_mcp_server/tools.py` 按现有 ONES 工具组合校验，不能只增加一个来源字段便安全接入代码知识。
- `backend/app/modules/authorization_center/application/service.py` 已按现行角色计算应用、Tool 和 `knowledge_base_ids`，可复用授权事实而无需仓库个人 ACL。
- `backend/app/modules/knowledge/application/managed_sync_pipeline.py`、`managed_sync_activation.py` 已有 ONES 候选、索引验证及同平台短事务激活路径；SVN 连续提交与代码事实分析需要独立用例，不能照搬 ONES 创建日窗口。
- `backend/app/modules/knowledge/domain/chunking.py` 当前为 ONES 文本 profile，需增加保留业务规则完整条件的内容投影。

上述为源码事实，不代表 SVN 能力或现有能力已完成真实环境验收。本提案其余新增内容均为待实现设计（Documented-intent）。

### 预计实施范围

- 后端知识模块、MCP 固定合同与策略、身份/角色授权投影、Agent/Application 工具组合、数据库迁移及 schema 事实源清单。
- 受限 SVN 同步与代码分析 worker、后台调度、知识分块/Embedding/Qdrant 索引及现有 Compose 运维接线；使用受管 Secret 引用和明确允许处理源码的分析模型连接。
- 现有管理端的知识来源配置、启停/重试/进度、安全缺口展示及角色知识库目录；业务时间轴优先通过 Agent 查询，不扩张为独立代码浏览或版本管理产品。
- 单元/合同、隔离 SVN 与数据库集成、恢复并发、浏览器和真实目标环境验收分开记录；更新相应测试分层清单。

本轮只创建本 change 的规划文档，不修改业务代码、canonical specs、已有 change 或部署配置。首批语言已确认是 C++、Vue、Java；具体语言/框架版本、构建上下文与目标 SVN 连接在接入时核实，不预设 Java 使用 Spring 或 Vue 的主版本，不宣称支持任意框架或已完成真实验收。

详细内容见 [设计](design.md)、[实施任务](tasks.md) 以及 [平台运维](specs/platform-operations/spec.md)、[工具与资源](specs/builtin-tool-resource/spec.md)、[身份授权](specs/identity-access/spec.md)、[业务应用](specs/business-application/spec.md) 四份增量规格。
