# governed-api-capability Specification

## Purpose
定义 ONES 与钉钉业务 MCP 的代码固定工具、Provider 请求、只读结果和受确认 mutation 合同。外部身份绑定与凭据生命周期见 `identity-access`，工具发布与精确 Job 授权见 `builtin-tool-resource`/`agent-model`，外部操作确认、Outbox、执行 claim 和审计主账见 `execution-delivery`。

## 实现依据与验证边界

当前合同以 `backend/app/shared/ones_tool_contracts.py`、`dingtalk_tool_contracts.py`、`services/ones_mcp_server/`、`services/dingtalk_mcp_server/`、`backend/app/modules/external_action/` 与 `backend/app/python_runtime/ones_result_bridge.py` 的代码为依据。测试依据包括 `backend/tests/test_ones_mcp_runtime.py`、`test_ones_basic_query_interfaces.py`、`test_ones_graphql_operations.py`、`test_ones_response_compatibility.py`、`test_ones_auto_collection.py`、`test_ones_testcase_collection.py`、`test_ones_query_condition_dictionary.py`、`test_ones_bug_create.py`、`test_ones_task_update.py` 和 `test_dingtalk_mcp_runtime.py`。

代码中的注册、Parser、预检、确认与 worker 实现可核对；离线替身、合同测试、容器启动和 OpenSpec 校验不证明真实 ONES 或钉钉验收。真实 ONES 查询、权限/布局、创建/更新及异常回查，真实钉钉目录、确认卡、待办/日历/AI 表格/消息结果与审计关联均须独立运行证据。特别是 ONES 缺陷创建依赖代码固定 `tasks/create_preflight` 合同；真实环境未提供可靠 ready/can_create/布局与引用校验时必须失败关闭，不能因代码已注册而宣称可用。Oracle 属于 `builtin-tool-resource`，本领域不补记任何真实 Oracle 验收。

## Requirements

### Requirement: 业务 MCP 只能发布代码固定受治理工具
`ones-mcp` 和 `dingtalk-mcp` SHALL 作为部署固定的标准无状态 Streamable HTTP MCP Server，注册代码明确的只读或受确认 mutation Tool。每个工具 MUST 有稳定 identifier、严格输入/输出 schema、有界结果、effect/confirmation policy 及适用的 operation、risk、target policy。模型、数据库、管理 API、Provider Profile 或环境开关不能引入任意 GraphQL/REST、动态 URL、任意工具或未注册写操作。

#### Scenario: tools list 精确授权
- **WHEN** Runtime 为已授权 Job 请求工具列表
- **THEN** Server 只暴露该 Job/Publication/当前角色授权且合同一致的代码工具子集

#### Scenario: 未注册 Tool 或执行元数据漂移
- **WHEN** 请求未注册 identifier，或 mutation 的 operation/确认策略/目标策略与固定合同不一致
- **THEN** 系统在解析业务 Credential 或 Provider I/O 前失败关闭

### Requirement: 业务 MCP 必须使用自身 audience 的当前 Job Principal
业务 MCP SHALL 验证平台签发的短时 Principal、精确 invoke scope、RUNNING Job、actor、应用、Publication、角色授权和 Tool Snapshot。不同 Server 不得复用 audience，File Principal 不能调用业务 MCP。ONES 只使用当前 Job 发起人的唯一启用 ONES 身份、可用 Credential 和默认 Team；钉钉使用同一企业和来源 Connector 的当前主体事实。

#### Scenario: 同群用户分别查询
- **WHEN** 两位用户先后发起 ONES 查询
- **THEN** 各自以本人绑定和默认 Team 执行，不使用群创建者、管理员或服务账号

#### Scenario: 身份或 Team 不可用
- **WHEN** 当前绑定缺失、歧义、停用、需要重验或默认 Team 已撤销
- **THEN** 返回安全身份错误，不回退其他用户、历史绑定或 Team

#### Scenario: 参数冒充主体
- **WHEN** Tool Input 提供 Token、Header、Team、Connector、operator 或当前用户身份覆盖值
- **THEN** 严格 schema 或规范化拒绝整个调用；作为显式业务目标允许的 ID 不改变执行主体

### Requirement: ONES Provider 请求与业务编排必须由代码固定
ONES Operation MUST 明确 method/path/query/body、响应解析与单位，HTTP Client 只执行固定 GET/POST 并限制单请求超时和响应大小，不跟随重定向。只读 GraphQL 文档集中保存在代码资源中，由固定 Operation 引用；mutation 预检/回查文档同样由代码拥有。REST 迭代、时间线、用户与角色成员接口必须保持各自协议，不能伪装为 GraphQL 或允许通用网络执行。

#### Scenario: 固定 GraphQL 查询
- **WHEN** 已授权 Tool 查询工作项
- **THEN** 使用代码固定 Team 路径、查询类型 t、GraphQL document 与服务端构造变量，筛选值不拼进文档

#### Scenario: 输入改变网络合同
- **WHEN** 参数试图指定 URL、method、path、query string、fragment、Header、operation code 或原始 Provider body
- **THEN** schema/Operation/HTTP Client 在外部连接前拒绝

#### Scenario: 多步 Service 编排
- **WHEN** 某 Tool 需要多个固定 Operation
- **THEN** 调用顺序、关联与空结果处理写在业务代码中，不从数据库或模型配置任意编排

### Requirement: ONES 401 只允许一次受控凭据刷新
ONES 查询首次返回 401 时 SHALL 以当前加密登录材料重新登录一次，严格核对原 subject 与默认 Team，以 Credential revision 条件更新 Token 并最多重试原查询一次。其他实例已更新 revision 时使用当前新凭据；身份变化、刷新失败或再次 401 必须要求本人重验，不更换执行主体。

#### Scenario: 并发实例已刷新
- **WHEN** 处理 401 时当前 Credential revision 与首次请求不同
- **THEN** 使用较新凭据重试，不覆盖其 revision

#### Scenario: 刷新后再次未授权
- **WHEN** 重试仍返回 401 或新登录主体/Team 不一致
- **THEN** 标记 REAUTH_REQUIRED 并失败关闭，不进行第二次登录

### Requirement: ONES 认证材料必须留在受信执行边界
ONES 服务 MAY 在进程内短暂解密登录材料和 Token，但 MUST NOT 返回或持久化到模型、Runtime、Tool 输出、日志或审计中的密码、Token、Principal JWT、Authorization/Cookie、密文与 nonce。受权限和保留期控制的 MCP 业务审计可保留合同允许的 provider identity 与完整有界业务请求，Provider 响应只保存白名单投影。

#### Scenario: 查询或刷新产生审计
- **WHEN** 请求成功、401 刷新或失败
- **THEN** 审计保留必要业务关联和安全结果，不含认证材料及原始未经投影响应

### Requirement: ONES 只读工具目录必须明确业务职责
代码 SHALL 注册工作项搜索、项目搜索、项目迭代、工作项类型、标准工作项筛选、自定义选项筛选、条件解析、工作项详情/时间线、Team 人员搜索/批量详情、项目角色成员、测试库/模块/计划/用例列表和用例详情工具。工具必须以业务 UUID 组合查询，不接受模型提供 Team、认证、GraphQL 文档或 Provider 操作类型。

#### Scenario: 组合查询迭代工作项
- **WHEN** Job 已冻结项目、迭代、类型与工作项工具
- **THEN** Agent 使用前序真实查询得到的 UUID 构造后续筛选，不猜测名称映射

#### Scenario: 旧 Job 请求新增工具
- **WHEN** 新代码包含某 Tool 但旧 Job 未冻结其精确合同
- **THEN** 服务拒绝，不因目录扩展自动扩大权限

### Requirement: 工作项搜索公开合同不暴露分页控制
`ones_work_item_search` MUST 只接受长度 1–200 的 keyword 与 `issue_type=demand|task|defect`。输出每项只含合法 number/name/type，集合累计上限 1000；不得公开或接受 limit/cursor，也不得把稳定类型猜测成真实项目工作项类型 UUID。项目、迭代和真实类型范围查询应使用对应工具。

#### Scenario: 合法搜索
- **WHEN** Agent 提交 keyword 和稳定 issue_type
- **THEN** 服务自动读取到终页或 1000 条，返回规范化集合与完整性元数据

#### Scenario: 使用旧分页输入
- **WHEN** 输入包含 limit/cursor，或旧 Job schema hash 与当前代码不一致
- **THEN** 调用在 Provider I/O 前失败，不静默适配旧分页协议

#### Scenario: 必填编号非法
- **WHEN** 任一工作项不能产生合法 number
- **THEN** 整次调用失败，不把其他项作为部分成功结果发布

### Requirement: 九类 ONES 集合必须自动有界收集
`ones_work_item_search`、`ones_search_projects`、`ones_list_issue_types`、`ones_query_work_items`、`ones_query_work_items_with_custom_options` 的累计上限 MUST 为 1000；`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans`、`ones_query_test_cases` 的上限 MUST 为 10000。模型不得收发 limit/cursor，REST 列表保留各自有界合同。集合输出包含 total、returned、cumulative_returned、truncated、pagination_limit_reached 与 untrusted_data=true，不返回模型续页游标。

#### Scenario: 测试资产超过一页
- **WHEN** 四类测试资产尚有后续且未达到 10000 与时间容量预算
- **THEN** 程序继续收集，不因短页或 total 值提前判定完成

#### Scenario: 达到累计上限
- **WHEN** 收集达到该工具固定上限且仍有后续
- **THEN** truncated 与 pagination_limit_reached 均为 true，Agent 不得声称已获得全量

#### Scenario: 其他列表超过 1000
- **WHEN** 普通项目/类型/工作项列表达到 1000
- **THEN** 仍按 1000 终止，不继承测试资产的 10000 限制

### Requirement: ONES 自动收集必须精确遵循 Provider 页合同
bucket 列表 MUST 使用固定不做业务分组的 groupBy、稳定筛选排序、最多 200 的 pagination.limit 与前页 endCursor；以 hasNextPage 判断完成，不以 totalCount 推断精确授权总量。不得裁剪 Provider 页后沿用该页尾游标。直接完整列表如测试库模块只单次读取并有界截取，不伪造分页。

#### Scenario: 短页仍有后续
- **WHEN** Provider 只返回 50 条且 hasNextPage=true
- **THEN** 按原 endCursor 继续，游标只在本次调用内使用

#### Scenario: 分页不稳定
- **WHEN** unstable=true、多个 bucket、重复记录/游标、空续页、count 不符或页长超过请求大小
- **THEN** 返回稳定安全错误，不发布部分集合为成功

#### Scenario: 收集预算耗尽
- **WHEN** 四类测试资产已耗尽 200 请求、其他集合 50 请求，或达到 90 秒/8 MiB 规范化结果预算
- **THEN** 有界失败，不无限翻页，不扩大授权或自动降低筛选精度

### Requirement: ONES 集合必须通过 Job 临时结果文件供模型读取
自动收集成功后 Runtime SHALL 把集合正文物化为 Job 受控只读临时结果文件，模型只接收元数据与 Read/Grep 提示。结果文件不赋予新 Workspace 权限，必须遵守 Sandbox 容量、只读与 Job 清理合同；中途失败不得发布成功文件。

#### Scenario: 收集到 10000 条测试资产
- **WHEN** 输出 schema、时间、字节和 Sandbox 容量校验全部通过
- **THEN** 文件可保存该集合，模型按返回提示按需读取，returned/cumulative_returned 为实际条数

#### Scenario: Provider 中途失败
- **WHEN** 后续页出现权限、协议或收集错误
- **THEN** 返回安全失败，不把此前页面包装成完整结果文件

### Requirement: ONES 响应必须白名单投影并按单位规范化
列表、详情、时间线和关联对象 MUST 校验必需字段并限制数量/字符串/正文，忽略非必要扩展字段，标记 untrusted_data=true。时间必须按各接口声明的秒/毫秒/微秒转换；迭代 progress 的 100000 倍定点值先除以 100000 再验证 0..100。只读 GraphQL 非空 errors 必须失败，不能返回部分 data 为成功。安全字段诊断只包含代码字段路径、期望约束和实际形状，不包含原值或原始 Provider 错误。

#### Scenario: 空可选关联
- **WHEN** 可选 owner/assignee/sprint 为 null、空对象或 uuid/name 都为空占位
- **THEN** 省略该关联且保留合法工作项；半空关联或类型错误仍失败，必填标识不放宽

#### Scenario: 时间线含富文本与链接
- **WHEN** Provider 返回富文本、附件访问 URL、头像或认证字段
- **THEN** 只输出有界纯文本、类型、时间和必要参与者摘要，不保留认证链接

#### Scenario: 固定点进度
- **WHEN** 迭代 progress 为 10000000
- **THEN** 输出为 100，而非把原值当百分比拒绝

### Requirement: 工作项筛选必须使用受支持的固定组合
`ones_query_work_items` SHALL 支持 keyword、project_uuid、sprint_uuid、issue_type_uuid、status_uuid、`status_category=to_do|in_progress|done`、assignee_uuid 与创建时间范围的代码组合。起止时间须合法有序；服务端选取固定通用/迭代 Operation，不支持的组合必须拒绝，不能删除筛选或换用近似查询。

#### Scenario: 迭代内已完成事项
- **WHEN** 调用提供唯一项目、迭代、工作项类型及 done 分类
- **THEN** 固定迭代 Operation 使用校验后的变量查询

#### Scenario: 组合无法精确表达
- **WHEN** 参数组合不被注册 Operation 支持
- **THEN** 返回输入错误，不扩大查询范围

### Requirement: 受管条件解析必须绑定当前 Team
`ones_resolve_query_conditions` SHALL 只按名称返回受管快照中的状态与单选/多选自定义选项，快照包含 schema version、来源 Team、采集时间和摘要，并必须匹配当前 Principal Team。输出有界候选字段/选项 UUID 与名称，不泄露 Provider 筛选键、整份字典、人员/项目/迭代列表或原始抓取。

#### Scenario: 中文名称匹配多个选项
- **WHEN** 名称在同 Team 快照内有多个候选
- **THEN** 返回全部有界候选供消歧，不选择第一项

#### Scenario: Team 不匹配
- **WHEN** 当前 Team 与快照来源不同
- **THEN** 返回任何映射前失败，不回退旧快照或个人抓取文件

### Requirement: 自定义选项查询必须验证字段与选项归属
`ones_query_work_items_with_custom_options` MUST 作为独立 Tool，在标准筛选之上要求至少一个有界 custom_option_filters，每项只含字段 UUID 和选项 UUID 集合。当前 Team 字典必须验证字段类型与选项归属，再确定性编译为固定 GraphQL filterGroup；Agent 不能提交自由 JSON、原始筛选键或动态文档。

#### Scenario: 合法自定义选项
- **WHEN** 字段为受管单选/多选且选项属于该字段
- **THEN** 服务端生成固定字段筛选并沿用集合限制

#### Scenario: 选项跨字段
- **WHEN** 合法选项 UUID 被用于另一个字段
- **THEN** Provider 调用前拒绝，不忽略错误条件

### Requirement: ONES 人员查询必须使用安全摘要与固定关联
`ones_get_users_by_uuids` MUST 只接受 1–100 个唯一合法 UUID，以当前 Team 的固定 users POST 返回 UUID/姓名。`ones_list_project_role_members` 只接受 project_uuid，先固定角色成员 GET，再去重成员 UUID 进行 users POST，按原角色顺序关联姓名，输出有界 roles/member 摘要。

#### Scenario: 角色成员为空
- **WHEN** 角色列表或全部成员为空
- **THEN** 返回合法空结果，不发无必要 users 请求

#### Scenario: 成员回查缺失
- **WHEN** users 响应缺少角色所引用成员
- **THEN** 整次调用失败，不静默丢失成员或猜测姓名

#### Scenario: 额外人员字段
- **WHEN** Provider 返回邮箱、电话、部门、头像、MFA 等字段
- **THEN** 人员工具只投影规定的 UUID/姓名，不输出原始对象

### Requirement: 测试资产必须保持库模块计划用例边界
测试库、库内模块、测试计划、模块/计划用例列表与用例详情 SHALL 为独立只读工具。`ones_query_test_cases` 的 source 必须为 module 或 plan 并提供 source_uuid；module 同时要求 library_uuid。系统不能猜测 UUID、把测试资产混入普通工作项或把不存在 continuation 的模块列表当可分页接口。

#### Scenario: 按模块查询
- **WHEN** source=module 且 library_uuid/source_uuid 合法
- **THEN** 使用固定模块用例 Operation，返回有界规范化用例身份

#### Scenario: 模块缺少库
- **WHEN** 模块模式没有 library_uuid
- **THEN** 连接 Provider 前拒绝

### Requirement: 运行查询字典与测试替身必须隔离真实抓取
运行快照 SHALL 通过确定性维护同步步骤只提取受管状态/选项和非敏感版本元数据，输入缺少 Team、采集日期或合法结构时不得覆盖原快照。生产、测试和 Mock 运行代码 MUST NOT 读取 `ones_mock/ones/` 原始抓取。仓库不提供可部署 ONES Mock；测试替身只存在测试边界，不监听网络或被生产导入。

#### Scenario: 生成条件快照
- **WHEN** 显式维护同步读取合法源材料
- **THEN** 同输入生成同字节及摘要，排除人员、项目、迭代、Header、Token、Cookie 与原始响应

#### Scenario: 离线验收
- **WHEN** 测试只使用合成 ONES fixture
- **THEN** 记录离线合同边界，不注入模拟身份到真实链路或声称真实 ONES 验收

### Requirement: ONES mutation 只允许单个缺陷的创建或更新提案
`ones_create_bug` 与 `ones_update_task` MUST 分别声明 `effect=mutation`、`external_action_card_v1`、固定 `ones.task.create`/`ones.task.update` operation 与单个新/现有缺陷目标策略。Tool 首次调用只准备 Action Intent，来源须为可验证的钉钉 Job，包括 dingding_stream；Web/后台来源不可借参数补足来源。调用不得接受 Provider URL、身份、Team、field UUID/type、原始 field_values、任意 HTML 或其他未声明控制字段。

#### Scenario: 提出合法缺陷操作
- **WHEN** 新 Job 的角色、Publication 与 Snapshot 显式授权对应 mutation 且钉钉来源事实完整
- **THEN** 只生成该单个缺陷的待确认提案，原用户确认前 Provider 写入次数为零

#### Scenario: 非缺陷或批量操作
- **WHEN** 请求创建其他工作项类型、批量更新或更新不是缺陷的 Task
- **THEN** 拒绝且不创建 Intent

### Requirement: 缺陷创建字段必须完整有界并保留来源
创建提案 MUST 包含标题、project_uuid、纯文本 description、environment、assignee_uuid、defect_type_uuid、urgency_uuid、severity_uuid、discovery_difficulty_uuid、reproduction_probability_uuid、非空 product_uuids/product_module_uuids、discovery_stage_uuid、online_defect_uuid、historical_defect_uuid 与非空 affected_version_uuids。多选与可选 watcher_uuids 按首次出现顺序去重；字段缺失/null/空白/超界须拒绝。建议值仅来自当前消息、当前相关会话、版本化字段目录或本次 ONES 只读查询，必须保存安全来源类别并标记建议，不得补造事实或用长期记忆/其他用户上下文补全。

#### Scenario: 所有必填字段完整
- **WHEN** 字段类型、长度、引用与数量均符合固定 schema
- **THEN** 进入创建预检，重复多选 UUID 稳定去重

#### Scenario: 事实待补充或名称歧义
- **WHEN** 描述仍含待补充内容，或人员/项目/产品/模块/版本无法唯一确定
- **THEN** Agent 展示普通草稿并要求澄清，不生成正式 Intent/确认卡

### Requirement: 缺陷创建必须使用固定目录和可靠预检
代码审查的版本化 bug_create_field_catalog MUST 固定缺陷类型、字段 UUID/type、中文含义、值类型与静态选项。名称先从受管目录找唯一候选，不能唯一确定时才使用当前身份的固定只读查询；最终须通过真实 Provider 预检证明原 Team、创建权限、唯一缺陷类型、完整布局与全部引用有效，模块属于所选产品。项目可见或普通编辑权限不能代替创建权限；当前用户必须始终包含在最终关注者集合。

#### Scenario: 固定目录命中
- **WHEN** 名称精确命中目录唯一候选
- **THEN** 无需为名称解析额外查询，但确认前仍校验权限、布局和引用可用性

#### Scenario: 预检接口未就绪
- **WHEN** 固定 create_preflight 不存在，ready/can_create 不为 true，或字段布局与目录不匹配
- **THEN** 返回安全未就绪/布局错误，不创建正式确认卡或执行 add3

#### Scenario: 生成纯文本与富文本
- **WHEN** 创建描述为合法纯文本
- **THEN** 编译器生成固定纯文本字段与安全转义富文本，不接受任意 HTML、附件上传或临时下载 URL

### Requirement: ONES 确认卡必须完整显示可确认业务内容
ONES 提案 SHALL 复用来源 Connector 的 external_action_confirmation 模板与 providerName/operationName/targetName/detailText 合同，向原用户私聊发送独立卡片。创建卡显示全部中文字段、完整描述、关注者与建议标记；更新卡显示目标与每个实际变化的中文原值/新值。不得显示内部 field UUID/type、生成 HTML 或认证材料；完整内容超过 detailText 4000 字符须拒绝准备，不能截断后取得确认。

#### Scenario: 卡片预算不足
- **WHEN** 完整创建摘要或更新差异超过 4000 字符
- **THEN** 不创建 Intent/Outbox，要求缩短创建描述或拆分更新

#### Scenario: 用户要求编辑确认内容
- **WHEN** 用户修改待执行字段
- **THEN** 回到会话提出新参数并重新确认，不原地编辑旧 Intent

### Requirement: 创建修订必须显式建立提案链
创建完整新版本 MUST 使用独立 Intent、卡片和 outTrackId。只有用户明确修订或可靠引用上一确认卡时才能建立替代链；新版本与旧 PENDING_CONFIRMATION 转为 SUPERSEDED 必须原子提交。相似标题、相同字段或同会话不足以建立替代关系。

#### Scenario: 修改仍待确认版本
- **WHEN** 原用户明确修订且旧版本仍 PENDING_CONFIRMATION
- **THEN** 原子生成新 Intent 并使旧卡失效

#### Scenario: 旧版已经批准执行
- **WHEN** 旧版已 APPROVED/EXECUTING 或终态
- **THEN** 不替代、不取消、不继续同链创建，待结果后可另发独立更新

### Requirement: 创建执行必须冻结 UUID 并核验结果
创建 Intent MUST 在确认前生成并冻结唯一 Task UUID、原 ONES 身份/Team、目录摘要与业务请求。确认有效期为 15 分钟，原身份/Team 改变卡片失效。worker 获得唯一 claim 后重验当前授权、原身份、创建权限、布局、目录和全部引用，仅发送冻结 add3；之后按同一 UUID 回查全部确认字段。

#### Scenario: 成功并回查一致
- **WHEN** add3 合法成功且按冻结 UUID 的全部业务字段一致
- **THEN** Intent 才可 SUCCEEDED

#### Scenario: 超时冲突或 worker 中断
- **WHEN** 写结果不确定、UUID 冲突或恢复无法证明成功
- **THEN** 只按同 UUID 核验；一致可记核验成功，否则 FAILED_UNCERTAIN，不换 UUID、不自动重放创建

### Requirement: 缺陷更新必须采用严格语义 Patch
`ones_update_task` MUST 要求单个 uuid 和至少一个显式业务变更字段。未出现表示不修改，null 始终非法；只有目录明确允许清空的文本/数组可用空字符串/空数组，负责人、迭代、单选等没有明确清空合同的字段不得清空。标题同时映射 name/summary，描述从纯文本编译 descriptionText/desc_rich；不发送其他未出现字段。

#### Scenario: 只修改描述
- **WHEN** 用户明确要求改写并更新指定缺陷描述
- **THEN** Agent 只提交 uuid/description，准备原值与新值差异并等待确认，不把可复制文本当已更新

#### Scenario: 无变更或 null
- **WHEN** 请求仅有 uuid 或任一业务字段为 null
- **THEN** Provider 访问前返回字段级错误

#### Scenario: 允许清空
- **WHEN** 目录可清空文本或数组显式为空
- **THEN** 差异显示“清空”，编译器使用固定清空表达

### Requirement: 缺陷更新只能写受管字段目录
Team-scoped task_update_field_catalog MUST 把公开语义字段映射为固定 field UUID/type、值类型与清空策略，校验静态选项归属及动态人员/迭代/产品/模块范围。支持目录明确的标题、描述、负责人、环境、标签、解决人、用户集合、缺陷分类、迭代、产品模块、版本、处理方案/原因/结果与优先级等字段；状态、项目、工作项类型、创建人、编号、创建更新时间及任何未列入字段必须拒绝。只读查询可见性不能产生写权限。

#### Scenario: 同名字段多套映射
- **WHEN** 名称对应多套字段 UUID
- **THEN** 只接受受管目录明确的一套，不按名称猜测或回退

#### Scenario: 写关注者
- **WHEN** Patch 包含 watcher_uuids
- **THEN** 必须具备专用关注者更新权限，普通编辑权限不替代

#### Scenario: 目录发生漂移
- **WHEN** worker 当前目录版本/摘要与确认快照不同
- **THEN** 写入前终止，要求重新发起确认

### Requirement: 更新确认必须绑定当前 Task 差异和更新戳
准备更新 MUST 读取当前 Task、缺陷类型、项目、字段适用性、权限与 serverUpdateStamp，规范化比较并只保留实际变化。同 Job/Tool/原身份/Team/Task/更新戳/目录摘要/参数产生稳定 Intent 指纹；不同快照或参数必须独立确认。worker 写前重新读取，任何更新戳变化均使整张卡失效，即使变化字段不在 Patch 中。

#### Scenario: 实际无变化
- **WHEN** 所有规范化目标值等于当前 Task 值
- **THEN** 返回 no_update/无需更新，不创建 Intent 或卡片

#### Scenario: 重复同快照 Patch
- **WHEN** 同 Job 重复完全相同的快照与参数
- **THEN** 复用原 Intent，不重复创建卡片

#### Scenario: 无关字段也发生修改
- **WHEN** 确认后 serverUpdateStamp 已变化但 Patch 字段仍相同
- **THEN** worker 仍拒绝陈旧确认，不自动合并或继续写入

### Requirement: update3 必须区分提交接受和业务核验
worker SHALL 仅在 update3 HTTP 成功、schema 合法且 bad_tasks 为空时视为提交被接受，并通过只读回查证明所有确认字段达到目标值后才记录 SUCCEEDED。明确部分失败终结为失败；超时、连接中断或 worker 中断后先回查，无法证明时 FAILED_UNCERTAIN，不自动重放写请求。

#### Scenario: HTTP 成功但 bad_tasks 非空
- **WHEN** update3 返回合法失败 Task 集合
- **THEN** 记录明确失败，不把 HTTP 200 当更新成功

#### Scenario: 超时后回查已达目标
- **WHEN** 只读回查证明全部确认字段与目标相同
- **THEN** 记录核验成功且不再次写入

### Requirement: ONES mutation 必须复用统一外部操作链
ONES mutation SHALL 复用 external_action_intent、Card Outbox、签名回调、claim/lease、恢复、统一审计与 external-action-worker，分离钉钉确认渠道和 ONES Provider 身份。审计保存完整有界确认业务快照、建议来源、前置条件、请求摘要及结果，不保存原始会话、私有推理或认证材料。链接只能从受信 ONES 地址与规范化结果构造。

#### Scenario: 多 worker 竞争
- **WHEN** 多实例取得同一已批准 Intent
- **THEN** 只有获得唯一数据库 claim 的实例进入 Provider 执行

#### Scenario: 创建或更新结束
- **WHEN** 操作终态产生
- **THEN** Intent 可关联 MCP Call、Tool Call、Job/Session、actor、Connector、Provider attempt 与结果卡，卡片如实显示核验结果

### Requirement: 钉钉工具目录必须按当前代码固定能力分类
钉钉 SHALL 注册通讯录/部门、本人待办、本人主日历、AI 表格、消息与本人工作通知的固定 Tool，并明确区分 21 个只读工具和 14 个 mutation。AI 表格只读集合包括搜索、sheet/field/record 查询及三个代码内置格式/能力参考；mutation 包括待办创建/更新/完成、日程创建/更新、AI 表格 sheet/field 创建更新及 record 插入更新、当前来源群消息、显式 userId 批量单聊和本人工作通知。环境 ACTIVE_PROFILES 或上游包新增能力不能扩大该目录。

#### Scenario: 请求目录外操作
- **WHEN** Agent 请求删除待办/日程、增删参会人、删除表/字段/记录、撤回、DING、自定义 Webhook 或任意 API
- **THEN** 返回不支持/未发布，不创建 Intent 或 Provider attempt

#### Scenario: 请求旧泛化机器人 Tool
- **WHEN** Agent 请求 dingtalk_send_robot_message
- **THEN** 当前目录不注册该旧 Tool，不把它兼容解释为任意用户或群发送

### Requirement: 钉钉只读 Tool 必须按目标策略解析身份
钉钉只读 Tool SHALL 在精确 Job/Publication/角色授权后直接返回有界结果，不创建 Intent。通讯录/部门按企业可见范围使用 staff ID；待办、日历及 AI 表格 Provider 调用需要当前 union ID；三个 static_official_reference Tool 返回代码内置有界版本化参考，不访问 Provider。身份补全只能使用同企业同 Connector 的可信详情接口并持久核验，不以管理员身份代替或把 union ID 缺失误报为角色权限不足。

#### Scenario: 本人未完成待办
- **WHEN** dingtalk_list_todos 已授权且 union ID 完整
- **THEN** 查询本人待办并按固定分页限制返回，不创建确认卡

#### Scenario: 查询 AI 表格参考
- **WHEN** 调用已授权格式或能力参考 Tool
- **THEN** 返回代码固定参考元数据，不把参考当成可执行任意 Provider 请求

### Requirement: 钉钉目录查询必须严格投影用户和分页事实
联系人与部门工具 MUST 使用来源 Connector 的企业 App Credential 及钉钉侧应用可见范围。用户结果只包含声明的稳定 ID、姓名、职务和有界组织字段，不返回手机号、邮箱、家庭地址或完整对象。searchUser 的字符串 userId 列表应直接投影非空 user_id；只有实际对象包含声明字段时才投影名称，不能伪造姓名。

#### Scenario: 搜索返回两个字符串 ID
- **WHEN** Provider 返回两个合法 userId 字符串且 hasMore=false
- **THEN** 返回两条 user_id、returned=2、truncated=false，不捏造名称

#### Scenario: 后续页存在
- **WHEN** hasMore、totalCount、页大小或 Provider cursor 表示还有结果
- **THEN** 返回有界分页与截断事实，不把当前页称为全企业结果

#### Scenario: 用户对象无法投影
- **WHEN** 成员既非合法字符串 ID 也非声明对象，或详情响应不完整
- **THEN** 返回稳定 Provider 合同错误，不生成空 ID 或猜测目标

### Requirement: 钉钉待办日历只能面向当前用户资源
待办 union ID、日历 union ID 和 calendarId=primary MUST 由 Principal 注入；模型仅提供有界业务字段、task/event ID。日历查询时间范围必须为正且不超过 31 天；全天日程使用固定 date 对象和排他的结束日期，不把普通文本或相同起止日期当有效全天事件。

#### Scenario: 当前主日历查询
- **WHEN** dingtalk_list_calendar_events 提供合法时间窗
- **THEN** 只查询当前用户 primary calendar

#### Scenario: 输入覆盖用户或日历
- **WHEN** 参数包含 union ID、calendar ID、企业或 Connector 覆盖字段
- **THEN** Provider I/O 前拒绝

### Requirement: AI 表格必须使用当前 operator 和精确资源
AI 表格 Provider Tool MUST 把当前 union ID 作为 operatorId，使用显式 base/sheet/record 标识和固定字段/记录值 schema。sheet/field 的创建更新与 record 插入更新属于受确认 mutation；准备前与执行前分别验证当前 operator 对目标 base 或 base/sheet 的可读性。单次记录 mutation 最多 20 条，字段/值/请求字节有界，不提供删除能力。

#### Scenario: 确认后权限撤销
- **WHEN** operator 已无法读取目标 base/sheet
- **THEN** worker 写入前失败关闭，不改投其他 operator 或资源

#### Scenario: 修改数据表名称
- **WHEN** 固定 sheet 更新接口返回空确认响应
- **THEN** 通过同一目标 get 回查名称后判定结果，名称漂移或目标不一致失败

#### Scenario: 记录返回身份漂移
- **WHEN** 更新响应记录 ID 或数量与冻结请求不一致
- **THEN** 不记为成功，返回安全合同错误

### Requirement: 按姓名发消息必须显式消歧
Agent SHALL 先用当前 Job 已授权的 dingtalk_search_users 找姓名候选，再用本 Job 的 dingtalk_get_user 核实，必要时查询部门。有多个候选的单数目标必须由用户选择；明确要求全部匹配者时只把全部已核实 userId 放入同一批。不得把历史 Job 拒绝当本轮授权事实；搜索/详情失败不得退回当前发起人、首项或工作通知。

#### Scenario: 同名候选
- **WHEN** 用户要求向某一人发送且核实后仍存在多个同名候选
- **THEN** 展示稳定 ID 与有界区分信息等待选择，消息 Intent 和 Provider 写次数为零

#### Scenario: 直接明确 userId
- **WHEN** 用户已提供明确稳定 userId
- **THEN** Agent 可调用已授权批量单聊 Tool，MCP 不隐式增加搜索或逐人详情预查

### Requirement: 批量单聊必须保留固定 Provider 映射
`dingtalk_batch_send_message_to_users_by_robot` MUST 只接受非空有序 user_ids 和仅含 title/text 的 msg_param，title 最多 200、text 最多 3000 字符；服务端注入 Connector robotCode，固定 msgKey=sampleMarkdown，把 msg_param 序列化为 msgParam JSON string 并调用固定 POST `/v1.0/robot/oToMessages/batchSend`。不得接受姓名、手机号、部门、全员标志、群目标或网络认证覆盖值。

#### Scenario: 准备明确用户整批消息
- **WHEN** 参数通过 schema 与全局 payload 字节限制
- **THEN** 保留成员及顺序，准备一个整批 Intent 与一张确认卡，不在准备时发送

#### Scenario: 未经证实的人数阈值
- **WHEN** 用户列表合法且仍处于全局 payload 上限内
- **THEN** 不虚构官方最多 20 人限制，不自动排序、去重、截断或拆批

#### Scenario: 全局 payload 超限
- **WHEN** 整批参数超过平台大小边界
- **THEN** 直接拒绝，不通过拆批绕过

### Requirement: 群消息和本人工作通知必须保持独立目标
`dingtalk_send_message_to_group_by_robot` SHALL 只发送当前 Job 可信来源群，群 openConversationId 与 robotCode 由服务端冻结；私聊来源不得调用它。`dingtalk_send_work_notification` 只面向当前用户 staff ID，Agent ID 从 Connector 注入。两者模型只输入有界 title/text，不得互换为显式人员单聊的回退。

#### Scenario: 当前群确认发送
- **WHEN** Job 来自有完整 openConversationId 的钉钉群且原用户确认
- **THEN** worker 向冻结来源群调用固定 groupMessages/send

#### Scenario: 私信能力未发布
- **WHEN** 用户请求给同事发私信但批量单聊工具缺失或目标未消歧
- **THEN** Agent 报告无法继续，不改用当前群、本人工作通知或其他 mutation

### Requirement: 钉钉 mutation 必须逐次确认并重新校验冻结目标
所有钉钉 mutation SHALL 先创建不可变 Intent，冻结 Tool/schema/operation、actor、Connector/企业、目标及完整有界业务输入；确认卡模板从来源 Connector 的 external_action_confirmation 用途解析并冻结 ID、合同版本与 Connector revision。原用户确认后 worker 获唯一 claim 并复核当前治理事实与目标，才能执行代码固定操作。批量单聊整批至多提交一次，结果不确定时不得自动重放。

#### Scenario: 模板配置变化
- **WHEN** Connector 的确认模板从 A 改为 B
- **THEN** 新 Intent 冻结 B，旧 Intent/Outbox 继续使用 A，不投递时动态回退

#### Scenario: 缺少模板或目标漂移
- **WHEN** 模板不兼容，或授权/actor/Connector/robot code/资源目标与冻结事实不符
- **THEN** 在 Intent 准备或写入前最早阶段失败关闭

#### Scenario: 原用户取消或重复点击
- **WHEN** 原用户拒绝或终态卡被重复点击
- **THEN** 不执行第二次 Provider 提交，拒绝状态保持零次写请求

### Requirement: 消息受理不等于最终送达
机器人消息的 processQueryKey MUST 只作为 Provider 受理事实，批量单聊须校验过滤/限流/非法收件人集合均属于请求成员，并返回 accepted/not_accepted 等有界计数。本人工作通知 task_id 只表示异步发送任务已提交；状态/结果 Tool 只能查询同 actor、企业、Connector 下成功发送 Intent 所创建的 task_id。不得以 Intent SUCCEEDED 或 HTTP 成功宣称消息已最终送达。

#### Scenario: 部分收件人未被接受
- **WHEN** Provider 返回合法 processQueryKey 及部分 filtered/flowControlled/invalid ID
- **THEN** 显示请求已受理和实际接受/未接受计数，不称全部成功送达

#### Scenario: 查询其他通知 task
- **WHEN** task_id 未关联当前 actor 在同 Connector/企业的成功通知 Intent
- **THEN** Provider I/O 前统一拒绝，不暴露任务是否存在

### Requirement: 钉钉 Provider 与审计必须固定且安全
钉钉请求 SHALL 使用代码固定 host/path/method、body 投影和响应 Parser，限制分页、时间、请求/响应字节与字段长度。只读输出与 mutation 执行结果按白名单投影；MCP 操作审计只记录必要标识、operation、授权、耗时、大小、状态和安全目标摘要，不保存认证、原始 Provider 正文、联系人敏感字段、消息/日程正文或 AI 表格值。用户已确认的业务内容仅在受控 Intent/确认展示合同中保存。

#### Scenario: Provider 返回权限或协议错误
- **WHEN** 上游错误包含原始描述或扩展字段
- **THEN** 映射稳定中文安全分类与有界合法 Provider code，不复制原始正文

#### Scenario: 受理与确认链关联
- **WHEN** 一次钉钉 mutation 完成确认与执行
- **THEN** Intent、卡片、MCP 审计、Job Tool Call 与唯一 Provider attempt 可准确关联，结果表述遵守该操作实际成功语义
