## Why

当前 ONES MCP 没有受治理的缺陷创建能力，Agent 即使已经从会话整理出完整缺陷信息，也无法在用户逐次确认后安全地创建 Bug。现有 `add-governed-ones-task-update` 又明确排除了创建 Task，因此需要一个边界独立、可审计且默认不授权的新 Tool，并复用既有钉钉 Action Intent 与外部操作 Worker。

## What Changes

- 新增代码固定的写入 Tool `ones_create_bug`，一次只通过固定 `POST /project/api/project/team/{team_uuid}/tasks/add3` 创建一个“缺陷”工作项；工作项类型由服务端固定，不开放任意 REST、GraphQL、原始 `field_values`、Provider 路径、Header、Team 或认证参数。
- 第一版只开放已确认的缺陷业务字段：标题、项目、描述、环境、负责人、缺陷类型、紧急程度、严重程度、发现难易程度、重现概率、产品、功能模块、发现阶段、是否线上缺陷、是否历史缺陷、影响版本；产品、模块和影响版本为非空、可多选 UUID 数组。描述只接受纯文本并由服务端安全生成 ONES 富文本。
- 所有必填业务字段在正式提案中必须有最终值。Agent 可以依据当前用户消息、同一钉钉会话中与本次缺陷直接相关的上下文及本次只读 ONES 查询生成建议值，但不得编造事实或在歧义时猜测；未完成内容只在普通会话中继续补充，不创建 Intent 或确认卡片。
- 负责人不默认当前 ONES 用户；关注者始终包含当前 ONES 用户，并允许追加经唯一解析的关注者。项目、人员、产品、模块、版本和枚举值只接收已解析 UUID；名称到 UUID 优先从版本化文档目录精确解析，文档找不到时才调用代码固定的 ONES 只读接口，同名或歧义时不得猜测。确认卡片只展示对应中文名称。
- 使用独立、版本化的 `bug_create_field_catalog` 固定接口文档及 `查询条件字典.yaml` 中已确认的字段 UUID、类型、中文含义和稳定选项 UUID；第一版不增加按实例或 Team 划分的 Profile，也不要求动态刷新静态枚举。
- 仅允许可验证的钉钉来源 Job 准备创建，继续使用 Web 后台配置的 `external_action_confirmation` 卡片模板。卡片完整展示全部中文业务字段、关注者以及“建议值”标记；超过 `detailText` 4000 字符时拒绝准备，不截断确认内容。第一版不支持图片、附件或卡片内表单编辑。
- 每个完整提案创建独立 Intent、卡片、`outTrackId` 和预生成 Task UUID，有效期为 15 分钟。明确修订或引用旧卡时，新版本将同一提案链内尚未确认的旧 Intent 原子转为 `SUPERSEDED`；已批准或执行中的创建不得替换或取消。
- 只有原提案发起人可以确认或拒绝。确认前及 Worker 写入前均复核内部用户、Job Tool 快照、业务授权、原始 ONES 身份、Team、Credential、创建权限、字段适用性和所有引用 UUID；身份换绑、Team 变化、权限撤销或布局漂移均失败关闭。
- 确认后始终使用同一预生成 Task UUID。成功响应后按 UUID 回查；UUID 冲突、超时或连接中断也只按该 UUID 核验，能够证明字段与确认快照一致才记为成功，否则进入 `FAILED_UNCERTAIN`，不得更换 UUID 或自动重放创建。
- 复用 `external_action_intent`、Card Outbox、签名回调、审计主账及 `enterprise_agent-external-action-worker`，不新增第二套 mutation 表、队列或 Worker。成功卡片只展示缺陷编号、标题、项目、负责人和受信配置生成的查看链接，不展示内部 UUID。
- 新 Tool 注册后默认不进入任何既有 Agent/Application Publication、角色授权或 Job 快照；管理员必须显式发布和授权，只有之后创建的新 Job 才可见。
- 当前没有真实 ONES 服务可供验收。本变更以 Mock、契约、迁移、确认回调、Worker、容器构建和 OpenSpec 校验作为本地完成证据；真实权限预检、创建、异常回查及完整审计链继续保持未验收，未取得可靠只读权限/布局接口前不得启用或宣称生产可用。

## Capabilities

### New Capabilities

- `governed-ones-bug-create`: 定义单个 ONES 缺陷的必填字段、建议值、逐次钉钉确认、提案替代、身份与权限复核、固定 UUID 创建、结果核验及安全审计行为。

### Modified Capabilities

- `governed-api-capability`: 在代码固定的 ONES Tool 集合中增加受逐次确认保护的 `ones_create_bug` mutation Tool，同时保留任意接口和未授权写入的禁止规则。

## Impact

- ONES MCP Manifest、Tool schema、字段目录、参数编译、Provider REST 客户端、只读预检/回查及操作审计。
- `external_action_intent` 状态和提案链、Repository/Service、Card Outbox、钉钉确认回调与原卡结果更新。
- `enterprise_agent-external-action-worker` 的 ONES 创建执行适配器、重新授权、结果核验和不确定终态。
- Agent/Application Publication、角色 Tool grant、Job Tool Snapshot 及管理端 Tool 展示。
- 数据库 migration、ONES Mock、容器裁剪/import smoke、回归测试与部署验收清单。
