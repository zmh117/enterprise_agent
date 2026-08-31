## ADDED Requirements

### Requirement: 钉钉 Tool 必须使用可复核的双官方基线
系统 SHALL 以固定版本的官方 `dingtalk-mcp` 包确定 Tool 功能语义，并以同一审计时点最新的官方钉钉 OpenAPI 文档或官方 SDK 确定 Provider method、path、请求和响应契约。基线 MUST 记录版本、校验值或 commit 及取证日期，不得把“官方 MCP 包最新版”自动解释为每个 HTTP 端点均为最新接口。

#### Scenario: 官方 MCP 与最新 SDK 的端点版本不同
- **WHEN** 官方 MCP YAML 仍引用 v1 或 legacy 路径而最新官方 SDK 提供等价 v2 接口
- **THEN** 系统先验证操作者身份、资源可见范围和响应语义等价，再决定是否使用更高版本 Provider 契约
- **AND** 契约矩阵记录该差异和迁移证据

#### Scenario: 更高版本接口的可见范围语义不等价
- **WHEN** 官方 MCP 的 v1 + operator 契约可访问同一资源，而候选 v2 契约在相同平台授权下被 Provider 拒绝
- **THEN** 系统使用官方 MCP 与官方 SDK 共同支持的 v1 + operator 契约
- **AND** 不得把该拒绝继续归因于用户未授权或用版本号更高覆盖真实兼容性证据

#### Scenario: 无法确认替代接口
- **WHEN** 维护者无法从最新官方资料证实某 legacy 接口存在等价替代
- **THEN** 系统不得猜测新路径或请求结构
- **AND** 该 Tool 保持 legacy 隔离或不进入新 Publication，并记录限制

### Requirement: 全部启用 profile 必须具有封闭契约清单
系统 MUST 对 `dingtalk-contacts`、`dingtalk-department`、`dingtalk-notable`、`dingtalk-calendar`、`dingtalk-tasks`、`dingtalk-robot-send-message` 和 `dingtalk-notice` 的全部官方 Tool 建立封闭清单。每项 MUST 标明官方名称与描述、系统 identifier、纳入或排除原因、effect、目标策略、method/path、请求字段、响应字段和证据基线；系统 Manifest 的注册集合和显式排除集合 MUST 与清单一致。

#### Scenario: 官方 profile 新增 Tool
- **WHEN** 固定官方基线包含清单未分类的 Tool
- **THEN** 契约校验失败并阻止新 Publication
- **AND** 系统不得默认把该 Tool 注册为可执行能力

#### Scenario: 系统 Tool 没有官方语义映射
- **WHEN** Manifest 中的钉钉 Tool 无法映射到官方能力或明确的平台扩展
- **THEN** 启动或发布校验失败关闭

### Requirement: 存在新式等价接口时不得继续调用旧 oapi
对每个 Provider operation，系统 MUST 使用最新官方资料中功能等价的新式接口；当 `api.dingtalk.com` 或更高版本接口已替代 `oapi.dingtalk.com` 时，新代码和新 Publication MUST NOT 继续调用旧路径。仅当最新官方资料仍明确支持 legacy 且没有等价替代时，系统 MAY 保留旧调用，并 MUST 在契约清单和测试中标注。

#### Scenario: 发现 legacy 调用已有新式替代
- **WHEN** 全量审计发现当前 operation 调用 `oapi.dingtalk.com` 且最新官方资料给出等价新接口
- **THEN** 实现迁移 method、path、参数和响应投影
- **AND** 防回归测试拒绝该 operation 再次使用旧 host

### Requirement: Provider 成功响应必须按 operation 严格解析
每个钉钉 operation MUST 声明允许的官方响应容器、分页字段和必需业务标识。HTTP 2xx 只有在识别到允许的结构后才能投影；已识别容器中的真实空数组 SHALL 返回成功空结果，未知结构、错误类型或缺少必需标识 MUST 返回 `dingtalk_response_invalid`，不得通过通用 fallback 静默投影为空。

#### Scenario: AI 表格数据表返回 value
- **WHEN** 获取全部数据表接口返回官方 `value` 数组且包含两个数据表
- **THEN** `dingtalk_list_aitable_sheets` 返回两个有稳定 `sheet_id` 的数据表
- **AND** `returned=2` 且 `truncated=false`

#### Scenario: AI 表格资源接口使用当前操作者
- **WHEN** 系统搜索、读取或写入 AI 表格的数据表、字段或记录
- **THEN** Provider 使用企业应用 Access Token，并由服务端把当前 Job 绑定的 unionId 注入为 `operatorId`
- **AND** 模型参数不得声明、选择或覆盖 operator 身份
- **AND** Action Intent 冻结明确资源 ID，worker 执行前确认 operator 与 Intent 的 `target_union_id` 一致并重新预检同一资源

#### Scenario: AI 表格非删除官方能力进入目录
- **WHEN** 新 Publication 启用 `dingtalk-notable` profile
- **THEN** 目录提供官方静态格式说明、数据表读取/创建/改名、字段读取/创建/更新及记录读取/新增/更新能力
- **AND** 创建或修改能力必须创建 Action Intent 并由原用户逐次确认
- **AND** 删除数据表、字段和记录继续显式排除

#### Scenario: 官方空列表
- **WHEN** 已识别的官方列表容器存在且值为空数组
- **THEN** Tool 返回成功空结果而不是 Provider 失败

#### Scenario: AI 表格包含初始化空记录
- **WHEN** 官方记录列表返回稳定 record ID 且 `fields` 为合法空对象
- **THEN** Tool 保留该空记录并继续返回其他记录
- **AND** 新增或更新记录的输入仍必须至少包含一个字段

#### Scenario: 2xx 响应结构漂移
- **WHEN** Provider 返回 HTTP 2xx 但没有该 operation 允许的容器字段
- **THEN** Tool 返回 `dingtalk_response_invalid`
- **AND** 有界诊断只记录 operation 和结构键名，不记录业务正文

#### Scenario: 响应超过 Tool 的有界上限
- **WHEN** Provider 返回的已识别列表条目数超过 Tool 输出上限
- **THEN** Tool 只返回上限以内的条目并令 `truncated=true`
- **AND** 不得在计算截断状态前提前裁剪 Provider 结果

#### Scenario: 成功响应缺少核心业务字段
- **WHEN** Provider 条目具有稳定 ID 但缺少该 operation 必需的名称、标题、时间、字段类型或记录字段
- **THEN** Tool 返回 `dingtalk_response_invalid`
- **AND** 不得向模型输出形式合法但业务不可辨识的空字符串或空记录

#### Scenario: 写入成功响应指向不同目标
- **WHEN** 更新日程回显不同 event ID，或 AI 表格插入/更新返回的 record ID 数量、唯一性或集合与请求不一致
- **THEN** Provider 执行按 `dingtalk_response_invalid` 失败关闭
- **AND** 系统不得使用请求参数伪造写入成功结果

### Requirement: 模型描述必须区分官方功能与平台治理限制
模型可见 Tool 名称、描述和输入 Schema MUST 准确表达对应官方 MCP 能力的对象、调用时机和参数语义；平台追加的主体解析、数据可见范围、目标补全、逐次确认和数量上限 MUST 作为治理限制单独表述。系统 MUST NOT 以官方相同或相似名称描述不同目标能力，也不得声称未实现的官方能力可用。

#### Scenario: Tool 只支持当前来源目标
- **WHEN** 平台扩展 Tool 只能从受信 Job route 解析当前来源群
- **THEN** identifier 和描述明确写出“当前来源群”
- **AND** 不使用会被理解为任意群或任意用户发送的官方通用名称

#### Scenario: Tool 被安全排除
- **WHEN** 官方 MCP 提供删除、Raw API 或未治理写入 Tool 而平台未纳入
- **THEN** 目录明确标记该能力未实现或已排除
- **AND** 模型和用户界面不得展示为当前可用

#### Scenario: 模型声称已创建确认卡
- **WHEN** 模型准备声明当前外部操作已创建确认卡或进入 `confirmation_required`
- **THEN** 当前 Job 必须存在对应确认型 Tool 的成功 Tool Event
- **AND** 没有实际 Tool Call、调用失败或调用被拒时，模型必须明确确认卡未创建
- **AND** Worker 必须拒绝投递缺少成功 Tool Event 支撑的当前确认卡成功声明，并记录有界审计

### Requirement: 机器人群聊和个人批量单聊必须使用独立官方语义
新 Publication SHALL 分别提供“使用企业机器人向群聊发送普通消息”和“使用企业机器人向一个或多个 `user_id` 发送单聊消息”的明确 Tool。群聊 Tool MUST 使用受信来源群或明确且可验证的 `openConversationId`；个人 Tool MUST 接受有界 `user_ids`。两者均必须创建 Action Intent 并由原用户确认，且不得互相降级、改用工作通知或按群名猜测目标。管理控制面 MUST 把官方 `ROBOT_CODE` 作为独立、非 Secret 的连接器字段维护，不得与工作通知 Agent ID 混用；运行时 MUST 从已发布连接器事实解析该值，模型参数不得提供或覆盖。

#### Scenario: 消息 Tool 缺少企业机器人 Code
- **WHEN** 应用草稿选择群聊或批量个人机器人消息 Tool，但任一钉钉来源连接器未配置 `ROBOT_CODE`
- **THEN** 应用完整校验失败并指出具体连接器
- **AND** 管理员可在连接器编辑页补齐独立的企业机器人 Code 后重新发布

#### Scenario: 按姓名给两名用户发消息
- **WHEN** 当前 Job 的用户搜索返回两个经核实的 `user_id` 且用户确认同时发送
- **THEN** 模型调用批量个人单聊 Tool 并把两个稳定 ID 放入同一 Action Intent
- **AND** 系统不改用工作通知或当前来源会话 Tool

#### Scenario: 给当前来源群发消息
- **WHEN** Job 来自钉钉群聊且用户要求在本群发送普通消息
- **THEN** 群聊 Tool 从受信 Job route 解析 `openConversationId`
- **AND** 模型参数不得声明或覆盖该受信来源事实

#### Scenario: 异步消息请求已受理但尚未证明送达
- **WHEN** 群机器人或个人批量接口返回 `processQueryKey`，或工作通知接口返回 `task_id`
- **THEN** Provider 结果和确认卡只声明请求已受理或异步任务已提交
- **AND** 不得使用“已发送成功”或“已送达”等最终结果措辞
- **AND** 个人批量结果按过滤、流控和无效收件人名单的并集计算未受理人数，不回显收件人 ID

#### Scenario: 新 Publication 遇到含混旧 Tool
- **WHEN** Tool identifier 或描述同时涵盖群聊和个人发送而无法唯一表达官方目标语义
- **THEN** 新 Publication 拒绝装配该 Tool
- **AND** 历史 Publication 和 Job 快照保持不可变

#### Scenario: 角色仍保存已下线的旧 Tool 授权
- **WHEN** 角色授权仍包含旧 Tool identifier，而当前应用 Publication 已不再装配该 Tool
- **THEN** 管理界面明确显示该历史授权并允许管理员取消选择
- **AND** 系统不得隐藏后继续提交，也不得放宽新 Publication 的目录校验
- **AND** 取消授权只创建新的角色授权 revision，不改写历史角色审计或既有 Job 快照

### Requirement: 官方契约升级必须通过版本化发布和真实验收
Tool identifier、描述、输入 Schema、effect 或目标策略的改变 MUST 形成新 Tool contract hash 和新 Agent/Application Publication；历史 Job 不得被原地升级。完成证据 MUST 包含静态全量契约校验、官方响应样例测试、受影响服务重建、新 Job 的真实只读结果以及每类已纳入 mutation 的确认后 Provider 结果。

#### Scenario: 仅容器健康但未创建新 Job
- **WHEN** 受影响容器均健康但没有新 Publication 和新 Job 的业务调用证据
- **THEN** 本 change 不得标记完成

#### Scenario: 真实调用受权限拒绝
- **WHEN** 最新接口返回官方权限拒绝
- **THEN** 验收报告将其归类为应用权限或可见范围问题
- **AND** 不得把它误报为响应结构错误、成功空结果或代码完成证据

#### Scenario: 官方 MCP 对照成功而候选接口拒绝
- **WHEN** 同一资源可由固定官方 MCP 契约成功读取或写入，而系统候选接口返回权限拒绝
- **THEN** 验收报告将其归类为 Provider 契约兼容性失败并阻止发布
- **AND** 系统必须先恢复已验证的官方契约，不得要求管理员重复增加不明权限
