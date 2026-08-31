## Context

平台当前以代码 Manifest 注册 28 个钉钉 Tool，覆盖通讯录、部门、待办、日历、AI 表格、机器人消息和工作通知。Provider 同时存在 `api.dingtalk.com` 新式接口与 `oapi.dingtalk.com` legacy 接口，且部分响应投影只接受本系统猜测的字段名。官方 `dingtalk-mcp@latest` 适合确定工具用途和模型描述，但该包自身仍含 v1/legacy 端点；因此不能把“官方 MCP 包最新版本”等同于“每个 Provider 端点都是最新接口”。

本 change 跨越代码 Tool catalog、Provider HTTP client、Action worker、Publication/Job 快照和部署验收。安全约束保持不变：模型不得提供 Connector Secret、当前主体或受信来源会话事实；mutation 仍只创建 Action Intent，确认后由 worker 执行。

## Goals / Non-Goals

**Goals:**

- 对全部已注册和显式排除的钉钉能力形成可复核的官方契约矩阵。
- 使用最新官方可用 Provider 接口并严格投影官方响应，消除“成功但伪装成空结果”。
- 让模型可见名称、描述、Schema 和目标语义与官方 MCP 能力一致，治理限制另行明确。
- 通过契约测试、新 Publication、新 Job 和真实 E2E 证明修复。

**Non-Goals:**

- 不照搬官方 MCP 的删除、Raw API 或自定义机器人能力；未纳入能力继续显式排除。
- 不把官方 MCP 包作为运行时依赖，也不允许运行时从网络动态下载 Tool 定义。
- 不迁移或改写历史 Publication、Job、Action Intent 和审计事实。
- 不使用、记录或回填用户曾在会话中暴露的凭据。

## Decisions

### 1. 官方来源采用双基线并记录精确版本

功能名称、调用时机和参数语义以审计时 `dingtalk-mcp@latest` 的精确 npm 版本及包校验值为基线；HTTP method、path、请求和响应以审计时最新官方 OpenAPI 文档与官方 SDK 的精确版本/commit 为基线。若同一官方 SDK 同时提供多个接口版本，只有在操作者身份、资源可见范围和响应语义已证实等价时才可迁移到更高版本；真实官方 MCP 对同一应用和资源成功、替代版本失败时，Provider 必须保持官方 MCP 所用契约并记录差异。

替代方案是直接转发官方 MCP 包。该方案会引入动态依赖、外部凭据边界和无法治理的 Raw Tool 集合，因此不采用。

### 2. 用单一静态契约矩阵驱动审计与测试，不引入动态目录

为七个启用 profile 的每个官方 Tool 记录：官方名称与描述、系统 identifier、纳入/排除原因、effect、目标策略、method/path、请求字段、响应字段和证据版本。运行时继续使用代码 Manifest；测试校验 Manifest 与矩阵的纳入集合和关键契约一致。

每个已注册 Tool 的模型描述拆成“官方功能”和“平台治理”两段，并用覆盖全部 28 个 identifier 的官方语义锚点测试约束。若平台只实现官方能力的安全子集，官方段保留原功能边界，治理段必须明确列出当前支持和不支持的参数，不能用笼统同名描述让模型误以为完整官方能力都可用。

替代方案是在运行时读取 YAML/SDK 生成 Tool。该方案会让上游更新未经发布即改变模型能力，违反 Publication 快照边界，因此不采用。

### 3. Provider 响应使用“已知结构严格解析”

列表接口按具体 operation 声明允许的官方容器字段，例如 AI 表格 sheets/fields 接受官方 `value`，records 接受官方 `records`。空数组只有在已识别官方容器且其值确为空时成立；HTTP 2xx 但结构未知、容器类型错误或必需标识缺失时返回 `dingtalk_response_invalid`，错误摘要只包含 operation 和结构键名，不包含业务正文。

替代方案是继续使用跨接口通用 fallback。该方案会把 Provider 漂移误判为空结果，已经造成现场错误，因此不采用。

### 4. 新式接口优先，legacy 只在官方仍无等价替代时保留

逐 Tool 搜索最新官方 SDK/OpenAPI。存在已证实语义等价的新式接口时迁移并按新请求/响应改测试；只有最新官方资料仍明确支持 legacy 且没有等价新式接口时才能保留 `oapi.dingtalk.com`，并在矩阵中记录限制和测试。任何无法证实的替代端点不得猜测实现，也不得把路径版本号更高当作等价证据。

AI 表格名称搜索使用 storage v2；数据表、字段和记录使用官方 MCP `1.1.21` 与当前官方 Go SDK `notable_1.0` 共同支持的 v1 路径。两类接口均要求 `operatorId`，且必须由当前 Job 已解析的钉钉 unionId 服务端注入，模型不得提供或覆盖。真实对照已证明同一 `baseId` 可由官方 MCP 的 v1 + operator 契约读取和写入，而本系统 notable v2 无 operator 契约在列数据表阶段被钉钉拒绝，因此两者不得再视为等价。

AI 表格 mutation 的 Action Intent 冻结 `base_id`、可选 `sheet_id/field_id` 及当前 operator 身份摘要；确认前预检和 worker 重授权必须把 operator 与 Intent 保存的 `target_union_id` 对齐，再访问同一明确资源。平台开放官方非删除能力：创建/改名数据表、创建/更新字段、插入/更新记录；三个官方静态格式说明以固定本地资源 Tool 提供。删除数据表、字段和记录继续排除。

### 5. 机器人消息按官方目标语义拆分

新 Publication 使用明确的群聊发送 Tool 和 `user_ids` 批量单聊 Tool；模型描述复用官方调用时机，并追加平台的受信目标解析和逐次确认约束。语义含混的 `dingtalk_send_robot_message` 不进入新 Publication；历史快照仍可按冻结合同读取，但不得被新 Job 复用。当前来源群可由服务端从受信 Job route 补全 `openConversationId`，任意群发送则必须有可验证的群标识解析能力；不得按群名猜测。

机器人群聊和个人批量接口返回的 `processQueryKey` 只证明钉钉已受理请求，工作通知返回的 `task_id` 只证明异步任务已提交。Provider 与结果卡不得把这些标识解释为最终送达；批量个人消息仅返回受理/未受理的有界计数，未受理人数按官方三类名单并集计算，避免重复计数并避免回显收件人 ID。

### 6. 发布与真实验收是完成条件

代码和测试通过后重建 `api-server`、`agent-worker`、`dingtalk-mcp`、Action worker 和相关 Runtime。创建新的 Agent/Application Publication 与新 Job，依次验证只读成功/真实空/权限拒绝/响应漂移，以及待办、日程、AI 表格数据表/字段/记录、群消息、批量单聊和工作通知的确认后执行。旧 Job 的结果不得作为新合同证据。

## Risks / Trade-offs

- [官方不同资料版本更新不同步] → 固定审计版本、记录差异，并由契约测试阻止无证据升级。
- [严格解析使以前“空结果”的调用变为失败] → 这是有意的失败关闭；错误码和结构摘要用于定位 Provider 漂移。
- [Tool 拆分导致旧 Agent 配置缺少新 identifier] → 保留历史快照，管理端显式创建新 Revision/Publication，不原地替换。
- [部分 legacy 能力没有新式等价接口] → 只在官方证据充分时保留并明确标注，不为了形式上的全 v2 编造接口。
- [真实 E2E 可能受应用权限和数据可见范围影响] → 分开报告合同失败、权限拒绝、可见范围空结果和业务写入结果。
- [把 notable v2 误当成 v1 + operator 的等价替代] → 固定官方 MCP/SDK v1 路径，所有 AI 表格资源访问均由服务端注入当前 operator，并以真实对照和目标漂移测试共同约束。

## Migration Plan

1. 固定并提交官方 MCP/OpenAPI/SDK 基线与全量契约矩阵，不含凭据。
2. 先增加官方响应样例的失败测试，再逐 profile 修正 Provider 和 Manifest。
3. 对 Tool identifier/描述/Schema 变化生成新 hash，更新新 Publication 可选目录；旧快照保持不可变。
4. 运行目标测试、全量相关测试、OpenSpec strict validation、Compose 配置校验和 Secret 扫描。
5. 重建受影响服务，创建新 Publication 与新 Job，完成真实 E2E 并保存有界证据。
6. 若部署失败，回滚到上一镜像和上一活动 Publication；不得回写历史 Job 或降级严格响应解析后继续发布。

## Open Questions

- 对最新官方资料仍只提供 legacy 接口的 Tool，逐项审计后才能确定最终保留清单。
- 任意群定向发送是否有受治理的群目录解析能力；若没有，本 change 只开放当前受信来源群和明确 `openConversationId`，不支持按群名猜测。
