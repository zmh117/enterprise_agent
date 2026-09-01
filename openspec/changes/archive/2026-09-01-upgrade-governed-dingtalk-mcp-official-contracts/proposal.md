## Why

当前 `dingtalk-mcp` 的部分 Provider 调用、响应归一化和模型可见描述没有同时对齐“官方 MCP 的功能语义”与“最新官方钉钉 OpenAPI 契约”：例如 AI 表格列表接口成功返回官方 `value` 字段时被误判为空，机器人消息工具也曾把官方区分的群聊与批量单聊能力描述成不同的目标范围。这会让只读结果与事实不符，并让模型选择错误工具或目标。

## What Changes

- 建立覆盖当前七个启用 profile、全部已注册 Tool 和显式排除 Tool 的官方契约清单；官方 MCP 包用于确认 Tool 功能语义，最新官方 OpenAPI/SDK 用于确认 method、path、参数和响应结构。若同一官方 SDK 同时提供多个版本，必须验证目标、身份与可见范围语义等价，不得仅按版本号选择更高版本。
- 将仍有新式官方替代接口的旧 `oapi.dingtalk.com` 调用迁移到最新官方接口；若最新官方资料仍只提供 legacy 接口，则记录证据并保持隔离，不虚构替代接口。
- 修正 Provider 响应归一化，严格接受已验证的官方字段结构；成功响应若结构未知或缺少必需字段必须返回明确的 `dingtalk_response_invalid`，不得静默伪装成空结果。
- 按官方功能语义重写模型可见描述和输入 Schema，并把平台附加的身份解析、可见范围、逐次确认等治理限制单独说明。
- AI 表格 profile 对齐官方 MCP 的 `notable_1.0 + operatorId` 访问语义，开放官方非删除能力及其三个静态格式说明 Tool；数据表、字段和记录写入仍逐次确认，删除能力继续排除。
- **BREAKING**：新 Publication 不再暴露语义含混的通用机器人消息 Tool；群聊发送和按 `user_id` 批量单聊分别使用与官方能力一致的明确 Tool。历史 Publication、Job 快照和审计事实保持不可变。
- 为每个 Tool 增加官方响应样例、错误结构、目标语义和端点版本的契约测试，并用新 Publication、新 Job 和真实只读/确认后写入链路验证，不以容器健康代替业务证据。

## Capabilities

### New Capabilities

- `dingtalk-official-contract-alignment`: 规范钉钉 Tool 的官方来源优先级、全量契约清单、最新接口、响应校验、模型描述、消息目标语义、版本迁移和真实验收。

### Modified Capabilities

- `builtin-tool-resource`: 要求业务 MCP Tool Manifest 冻结经过官方语义与 Provider 契约校验的描述、Schema、effect 和目标策略，并对破坏性目录升级生成新 Publication。
- `platform-operations`: 将固定 `dingtalk-mcp` 的就绪和发布门禁扩展为全部启用 profile 的官方契约测试与真实 Provider 验收。

## Impact

- 代码：`backend/app/shared/dingtalk_tool_contracts.py`、`services/dingtalk_mcp_server/`、Action worker、Tool catalog/Publication 快照和相关测试。
- 外部接口：钉钉通讯录、部门、待办、日历、AI 表格、机器人消息和工作通知 Provider 端点及响应结构。
- 发布：Tool identifier、描述或 Schema 变化将产生新 schema hash，并要求新 Agent/Application Publication 与新 Job；旧 Job 不被原地升级。
- 运维：需要重建受影响镜像，完成无 Secret 的静态契约验证，并在已轮换凭据的受控环境执行真实 E2E。
