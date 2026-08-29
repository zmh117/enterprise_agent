## MODIFIED Requirements

### Requirement: 角色授权中心不得授予未治理的写入型工具
系统 MUST 从角色可选能力目录排除写数据库、修改 Redis、执行 Shell、任意写文件、通用 HTTP/Raw API 或其它未声明确认策略的非只读工具。`platform-admin` 也不得通过角色页面绕过该风险边界。代码注册的固定业务 MCP mutation Tool 只有在 Manifest 声明受支持确认策略、Agent/Application Publication 显式冻结且运行时强制逐次确认时，才可作为业务 Tool grant 目标；该例外不得扩大 `tool-mcp` 基础设施 Tool 的只读边界。

#### Scenario: 客户端伪造写工具能力
- **WHEN** 客户端向角色授权 API 提交未知、动态或缺少确认策略的写入型工具编码
- **THEN** 后端拒绝整个授权区修改并记录安全校验失败

#### Scenario: 授权受确认保护的业务 mutation
- **WHEN** 角色授权请求选择代码注册、已发布且确认策略完整的 `dingtalk_create_todo`
- **THEN** 后端可以保存 Tool grant，但每次具体调用仍必须创建独立 Action Intent 并确认

### Requirement: Tool Manifest 必须声明执行副作用分类
代码 Tool Manifest SHALL 为每个 Tool 声明 `effect=read|mutation` 和 `confirmation_policy`，并 MUST 校验 read Tool 不绑定 mutation 确认策略、mutation Tool 必须绑定代码支持的确认策略。新 Job 快照 MUST 在既有 input schema hash 之外独立冻结并验证这两个字段；历史 schema v1 快照保持原有兼容读取，后续 retry 仍须经过当前代码 Manifest 与既有授权复核。

#### Scenario: 新增 ONES 修改 Tool 未声明确认
- **WHEN** 代码 Manifest 注册 `ones_update_work_item` 但 effect 或确认策略缺失
- **THEN** 启动、发布和 Job 快照校验失败关闭
