# 第三阶段：现场结构兼容与 Mock 下线（2026-09-09）

## 范围和证据边界

用户要求删除 Mock 干扰、对照 `ones_mock/ones` 的现场接口修复，并明确「本地没有 ONES，暂不连接」「不要关闭 ones-mcp」。随后收窄范围为恢复环境示例、只删除 Mock，明确不撤回接口修复。最终只保留接口修复、必要回归和 Mock 删除；环境配置及 ones-mcp 启动/健康逻辑恢复原样，不连接真实 Provider。

现场目录原样保留且继续被 Git 忽略。只提取字段、类型、单位、响应包裹和计数；不复制认证头、登录材料、人员标识、业务正文或原始响应到测试/日志/本证据。新回归使用独立合成值，不在测试运行时加载现场文档。

## 已复现的原因与修复

- 迭代样例 `sprint.sprints[].progress` 是定点整数，满进度为 10000000。旧 Parser 直接限制原值 0..100，样例的两条迭代均触发 `ones_provider_schema_invalid`。隔离进度字段后其他必填字段可通过。现在先除以 100000，再输出 0..100 百分比；公开 schema 允许保留小数，不截断到整数。
- 迭代 `start_time/end_time` 和测试用例 `createTime` 是秒，原统一毫秒处理会产生 1970 年附近日期。工作项时间和消息 `send_time` 是微秒；现在每个固定 Operation 显式声明单位，并保留微秒精度。
- 两种用例列表原先复制了较弱的 pageInfo 解析逻辑，且会裁剪超量页后保留原 endCursor，存在漏数据风险。现在复用共享页校验：拒绝 count/实际条数不一致、超过请求页大小、unstable、多 bucket 和错误类型；不裁剪后推进原游标。
- GraphQL 顶层非空 `errors`（含与部分 `data` 共存）现在返回 `ones_provider_graphql_error`，不伪装为完整结果或普通字段缺失。共享字段校验输出安全路径、约束、类型/空值/长度，不输出原值。
- Provider FAILED 事件现在保存安全 error/error_code，根 Tool FAILED 也保留相同原因。已有时间线展示路径继续生效，不恢复原始 Provider body 或堆栈展示。

官方单位参考：[迭代属性](https://docs.ones.cn/project/open-api-doc/project/sprint_field.html)、[属性数值](https://docs.ones.cn/project/open-api-doc/project/field.html)、[迭代接口](https://docs.ones.cn/project/open-api-doc/project/sprint.html)。现场内部接口结构与当前请求投影分别核对，不将公开接口与内部接口简单混同。

## 已注册接口核对矩阵

下列行号是现场文档中响应的起始行，仅供维护者定位，不代表已连接现场接口。

| 工具 / Operation | 结构证据 | 核对结果 |
| --- | --- | --- |
| 项目搜索 | `查看项目列表.md:39`，`data.buckets[].projects` | 项目字段可规范化；样例仅保留 3 条而 count 不同，作为节选，不据此放宽页校验 |
| 项目迭代 | `查看项目下迭代列表.md:25`，`sprint.sprints` | 确认并修复进度定点比例和秒级日期 |
| 工作项类型 | `查询工作项类型.md:29`，`data.issueTypeScopes[].issueType` | 7 条结构可解析；Markdown 含未转义换行，仅离线读取允许，生产 JSON 校验未放宽 |
| 工作项查询、自定义选项查询、旧关键词搜索 | `查询任务.md:77`、`按number查缺陷列表.md:48`，`data.buckets[].tasks` | 现存行满足当前摘要投影，工作项时间显式微秒；旧搜索复用相同页完整性校验 |
| 迭代工作项 Operation | `迭代缺陷.md:96`、`迭代story.md:72` | 字段可规范化；保留行数少于 pageInfo.count，为节选，不能证明真实完整分页 |
| 工作项详情/子项 | `查看任务（需求缺陷工单）详情.md:45`、`:218`；`查task的子任务.md:26`，`data.task` | 样例满足当前详情字段；`缺陷关联内容.md:30` 是较窄请求投影，不能当作完整详情响应 |
| 消息时间线 | `任务task的message，带时间线.md:22`，`messages` | 14 条，消息时间为微秒；系统事件可省略 text，保持现有空文本语义 |
| 用户查询和批量人员 | `查用户.md:25`、`查询指定项目下的人员.md:36`，`users` | UUID/名称摘要结构兼容；仅安全字段进入返回 |
| 项目角色成员 | `查询项目关联人员.md:27`，`role_members`；后续 users 响应 | 角色、成员 UUID 列表及批量人员响应兼容，既有唯一性/大小保护保持 |
| 测试库 | `查找用例库.md:29`，`data.buckets[].testcaseLibraries` | 1 条结构通过 |
| 测试模块 | `查用例库的路径.md:34`，`data.testcaseModules` | 3 条直接列表结构通过；不伪造 Provider cursor |
| 测试计划 | `测试计划列表.md:29`，`data.buckets[].testcasePlans` | 16 条实体结构兼容；原请求只选 totalCount，当前文档已请求完整 pageInfo，不将旧投影缺字段归因于服务错误 |
| 模块下用例 | `按路径uuid查找其下的全部用例.md:76`，`testcaseCases` | 仅保留 3 条、报告总量更大，不能用作完整页；接入统一完整性校验 |
| 计划下用例 | `查询测试计划下的用例.md:65`，`testcasePlanCases[].testcaseCase` | 473 条完整样例按对应请求边界解析；当前单页 200 请求不能默默接受并裁剪此超量页 |
| 用例详情 | `按用例的uuid查用例详情.md:52`，`testcaseCases/testcaseCaseSteps` | 修复秒级 createTime；详情、步骤投影兼容 |
| 创建/更新及读回 | `新增bug-task.md:298`、`更新task.md:248`、`查看task的info.md:21` | tasks/bad_tasks、标识/编号/字段列表等结构匹配现有 Parser；未发出写入，不代表完整 preflight/readback 的真实验收 |
| 查询条件解析 | 已受控静态资源 | 不调用 GraphQL/REST，未改变字典、Team 约束或发布权限 |

`登录.md` 的认证材料未纳入采样；功能模块、加评论等未独立注册的接口只确认其不在本次工具范围，不新增 API 或扩大写权限。

没有原 Job 三次带历史 created_to 条件失败的原始响应，现有工作项样例未复现那三次失败。不能断言它们与迭代 progress 同源，或宣称所有现场 schema 错误已经消失；新增安全字段定位用于后续精确排查。

## Mock 移除和运行方式

- 删除可部署 Mock 的 Dockerfile、依赖清单、包入口和服务说明；进程内合成替身迁至 `backend/tests/support/ones_provider.py` 与独立合成配置，不读取环境 Provider 地址，不监听端口。
- 原 `ones_mock/docker-compose.ones-mock.yml` 仅删除 ones-mock 服务块，MySQL、SQL Server、Redis、seeder、项目名称、构建上下文及外部数据卷均未改变；原脚本入口保留，不移动测试基础设施。
- 删除唯一 service=ones-mock 的运行容器；未删除其他测试容器、镜像或数据卷。源文件可从 Git 恢复。
- 主 Compose、`.env.example`、本地未跟踪 `.env` 的六个 ONES 配置项均恢复原值；身份/凭据数据库记录未修改。
- ones-mcp 保持原启动和健康依赖；撤回额外的空 Provider 启动模式、health 字段及其测试，恢复原有 origin/allowlist/HTTPS 校验。配置文件中保留原地址并不代表 Mock 仍运行，也不代表进行过 ONES 接口探测。
- 本地 Compose 验收移除模拟 ONES 身份注入与 Mock 场景，明确 local_non_ones 和 skipped_scenarios；不修改旧 Job 或历史审计。

## 本地验证

- 最终范围扩展回归 **327 passed**：全部 `test_ones_*.py`、进程内替身、架构/Compose 安全、测试分层、Runtime/Agent 审计。新增结构/单位回归 22 项，已撤回与额外未配置模式有关的 3 项测试。
- Ruff 通过；`MYPYPATH=backend mypy --explicit-package-bases services/ones_mcp_server backend/app/acceptance/python_runtime_composition.py backend/app/shared/ones_tool_contracts.py`：48 文件通过。本轮未运行全 backend mypy，不将既有全量问题声称为已解决。
- 主 Compose、独立测试数据 Compose、Python runtime acceptance overlay 配置校验通过；本 change 严格 OpenSpec 校验、git diff --check 通过。
- 接口修复曾重建并替换 ones-mcp、api-server、agent-worker、python-agent-runtime、external-action-worker；最终撤回额外配置后，重新构建/替换 ones-mcp、api-server、external-action-worker，并核对原配置与健康状态。未部署 Mock，不运行真实 ONES 场景。
- 容器内纯合成解析确认满进度输出 100、迭代/用例日期输出正确的 2026 年秒级时间。原 ones-mcp `/health` 与安全校验保留，无实际 Provider 出站。
- service=ones-mock 容器不存在，宿主机 19121 无监听。

## 保留待验收

真实 ONES、真实创建时间历史筛选、足量数据多页、写入前置校验与读回，以及重新发布 Agent/Application 后的新 Job / 模型 / 时间线联调均未执行。第 5.3、6.6 项继续待验收，不以离线测试或服务健康替代。此次进度输出改为 number 不改变当前仅基于 input schema 的 hash；既有第二阶段输入契约升级仍须通过新 Publication 生效。
