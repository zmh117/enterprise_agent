## ADDED Requirements

### Requirement: ONES 知识可读性必须复用本人详情合同
ONES 服务 SHALL 为固定内部桥提供有界只读投影，复用现有本人身份、Credential、默认 Team、详情 Operation、响应解析、超时/容量限制及一次 401 刷新合同，不注册第三个模型 Tool、不复制登录客户端、不假设 Provider 已有批量权限 API。内部入口 MUST 使用 ONES 自身 audience、精确详情 Tool Snapshot 和当前授权，独立覆盖认证中间件、限流、请求大小及安全审计。

可读性 MUST 基于实际有效详情响应并核对 task UUID、受信实例/Team 上下文和 source_project_id；HTTP 200、项目可见、UUID 外观或共享凭据成功 MUST NOT 单独构成允许证据。投影仅返回可读性和必要归属核对结果，不向知识服务返回详情正文。

#### Scenario: 返回 HTTP 200 但业务内容不可用
- **WHEN** Provider 返回空节点、错误结构、权限错误或不匹配的工作项 UUID
- **THEN** 系统不判为可读，不返回该候选，不以 HTTP 状态单独授予权限

#### Scenario: 工作项项目发生变化
- **WHEN** 当前详情所属项目与离线修订的 source_project_id 不一致
- **THEN** 系统不返回旧候选引用，不以同名项目或旧文本绕过来源核验

#### Scenario: 可读性访问触发凭据刷新
- **WHEN** 本人详情访问首次返回 401
- **THEN** 仅按现有本人身份/默认 Team 合同受控刷新一次，失败或再次 401 时要求重验，不增加另一层刷新循环

### Requirement: 知识 Provider 失败必须与无匹配结果区分
知识检索 SHALL 区分明确不可读/不存在、预算截断和 Provider/身份故障。超时、限流、5xx、响应合同错误或凭据失效 MUST 返回稳定中文安全错误且不附候选内容，不能当成成功空集合或证明没有相关缺陷。仅固定候选限额或预留返回复核时间不足、硬截止尚未到达且依赖没有报告故障时 SHALL 允许返回已确认可读的部分结果并标记有界 partial；硬截止到达 MUST 丢弃业务结果。原始 Provider 响应、业务正文、认证材料及含敏感内容的异常 MUST NOT 进入通用错误和日志。

#### Scenario: ONES 服务暂时不可用
- **WHEN** 某候选可读性检查收到 429 或 5xx
- **THEN** 调用返回依赖不可用类安全错误，不返回候选、不声称未找到相关缺陷

#### Scenario: 到达固定检查预算
- **WHEN** 已确认部分候选可读，达到工作项数或预留返回复核时间阈值，硬截止尚未到达且没有 Provider 故障
- **THEN** 仅返回已确认的命中及通用 partial，不返回被拒绝数量或未经核验的候选

### Requirement: 知识引用必须通过当前 ONES 工具回源
ONES 知识命中 SHALL 使用本地 source_id、task UUID 及内部版本/证据引用；不要求预先确认 ONES 地址或 Team，以本人当前默认 Team 的真实详情响应完成可读性和 UUID/项目核对定位；可选编号 MUST 经过当前归属验证。发布知识检索的 Agent/Application 有效工具子集 MUST 同时包含 `knowledge_search` 与 `ones_get_work_item_detail`，运行时再次复核授权。Agent SHALL 使用现有详情 Tool 以本人身份读取当前内容，MUST NOT 根据缓存正文、任意链接或模型猜测构造新的 Provider 入口。引用和正文 MUST 作为不可信业务数据，不得改变系统指令或授权规则。

#### Scenario: 检索后权限被撤销
- **WHEN** 搜索曾返回可读引用，但用户在调用详情前被 ONES 撤权
- **THEN** 详情工具按当前权限拒绝，Agent 不能以先前引用或离线正文作为读取授权兜底

#### Scenario: 未发布详情工具
- **WHEN** 草稿包含 ONES 知识检索但有效 Tool 子集缺少详情 Tool
- **THEN** 发布拒绝并说明依赖，不自动为角色或旧 Publication 新增工具

#### Scenario: 业务内容含提示注入
- **WHEN** ONES 正文或工作项文本要求更换模型、读取其他知识库或输出凭据
- **THEN** 系统继续执行固定工具与数据边界，不把业务文本作为可执行授权或平台指令
