## Why

当前已完成的钉钉 MCP MVP 只提供 `dingtalk_create_todo`，无法覆盖联系人、部门、本人待办查询、本人日历、AI 表格、机器人消息和工作通知等日常场景。官方 `ACTIVE_PROFILES` 会动态装载大量工具并允许 YAML 决定 URL、Method 与参数，不符合本平台代码 Manifest、Publication、角色授权、Job 快照和逐次确认边界，因此需要把首批高价值能力收敛为固定、可审计的 Phase 2 工具集。

## What Changes

- 将 `dingtalk-mcp` 从单工具骨架扩展为代码注册的 27 个工具：保留现有 `dingtalk_create_todo`，新增 18 个只读工具和 8 个受确认保护的 mutation 工具。
- 新增联系人/部门查询、本人待办查询、本人主日历查询、AI 表格及字段/记录查询、工作通知进度与结果查询；所有列表、游标、时间范围、批量大小和响应均有界。
- 新增本人待办更新/完成、本人主日历日程创建/更新、AI 表格记录新增/更新、当前会话机器人消息和当前用户工作通知；每个具体参数集继续创建独立 Action Intent，并由原用户在钉钉卡片确认后异步执行。
- 泛化现有 DingTalk Principal、MCP 审计和外部操作 worker，使其按固定 Tool identifier、schema、effect、confirmation policy 与 operation code 授权和分派，不再写死创建待办。
- 用户、企业、Connector、`unionId`、AI 表格 operator、主日历、当前会话和当前通知接收人均由当前 Job 与持久平台事实解析；模型不得提交身份、Credential、Provider URL、HTTP Method/Header、`ACTIVE_PROFILES` 或任意消息目标。
- 钉钉通讯录读取受企业应用可见范围限制；AI 表格读写必须以当前用户 operator 访问目标 base/sheet，并在 mutation 执行前再次验证；机器人消息只允许当前 Job 来源会话，工作通知只允许当前用户本人。
- 外部操作确认卡模板改为按钉钉应用 Connector 配置的用途绑定；当前只开放“外部操作确认卡片”这一代码定义用途。新 Action Intent 将模板 ID、模板合同版本和 Connector revision 冻结到 Card Outbox，后续修改配置不得改变既有 Intent。
- 本阶段不提供删除、撤回、自定义机器人 Webhook、DING、任意用户/部门群发、AI 表格 sheet/field 结构修改、日程删除或参与人修改；这些能力不得因官方 Profile 已启用而自动出现。
- 本 change 的 apply 前置条件是 `add-governed-dingtalk-mcp-mvp` 先同步并归档到 canonical specs；在前置条件满足后必须重新读取 canonical、复核本 change 的 delta 并严格校验，未满足前不得实施。

## Capabilities

### New Capabilities

- `dingtalk-mcp-tool-suite`: 定义 Phase 2 固定工具目录、输入输出边界、只读调用、受确认 mutation、可信目标解析、Provider 合同和明确排除项。

### Modified Capabilities

- `identity-access`: 扩展钉钉业务 MCP 的逐工具 Principal、企业/Connector/外部身份复核，以及通讯录、日历、AI 表格和消息目标的数据范围边界。
- `channel-conversation`: 将机器人主动消息目标限定为当前 Job 冻结的钉钉来源会话，并禁止模型提供任意会话或机器人身份。
- `platform-operations`: 增加 Phase 2 所需钉钉权限、工作通知 Agent ID、固定 Provider 操作注册表、健康就绪与分 Profile 真实验收要求。

## Impact

- 影响 `services/dingtalk_mcp_server/` 的合同、Tool registry、Principal、Provider clients、只读执行器、mutation 准备器和 external action worker；现有 `dingtalk_create_todo` 合同与成功/拒绝语义保持兼容。
- 影响代码 Tool Manifest、Agent/Application Publication、角色工具目录、Job Tool Snapshot、MCP 审计和外部操作卡片安全摘要；不引入动态 MCP Server、通用 HTTP/Raw API 或用户 OAuth。
- 影响 Connector 非敏感元数据和管理端校验：工作通知需要固定数值 Agent ID；外部操作 mutation 需要已发布且符合固定字段合同的确认卡模板 ID；Client Secret、Access Token、Principal JWT 和原始 Provider 正文继续不得进入模型、Job、卡片、日志或审计。
- 需要新增单元、合同、集成和真实 E2E 验收，至少覆盖每个只读 Profile、每类 mutation 的同意/拒绝、目标越权、权限漂移、重复点击和 Provider 不确定失败。
