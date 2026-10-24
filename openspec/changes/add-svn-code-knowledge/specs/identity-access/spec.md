## ADDED Requirements

### Requirement: 代码知识必须复用现有角色范围且不要求个人仓库身份
代码知识业务访问 SHALL 仅使用现有启用用户、有效角色成员、应用访问、精确 MCP Tool grant、知识库范围和显式拒绝计算授权，并受 Agent/Application Publication 与 Job 工具快照上限约束。规则、表字段、变化时间轴及业务引用 MUST 使用相同知识库授权，不引入独立知识 ACL、文档 ACL 或个人 SVN 身份。后台 SVN 采集凭据只用于来源连接，不得授予用户业务读取权限；平台管理权限也不得替代业务授权。跨角色计算 SHALL 保留现有完整应用授权记录与范围语义，不跨不匹配记录拼接出额外知识库权限。

#### Scenario: 角色已授予代码知识访问
- **WHEN** 当前应用的有效角色授权覆盖所需工具与代码知识库，用户没有 SVN 或 ONES 个人身份
- **THEN** 允许继续代码知识查询，且相同范围适用于规则、字段和时间轴

#### Scenario: 用户只有 SVN 或管理权限
- **WHEN** 用户有仓库访问权限或平台管理角色，但没有目标应用下的知识库业务授权
- **THEN** 拒绝业务读取，不能用后台采集身份或管理身份替代

#### Scenario: 等待期间撤权
- **WHEN** 内容查询等待 SVN 知识更新期间，角色成员过期、Tool/知识库授权被撤销或命中显式拒绝
- **THEN** 终止该读取并拒绝返回，更新完成也不复用此前授权

#### Scenario: 新增知识库或工具
- **WHEN** 同步接入了新知识库或平台注册了新代码知识工具
- **THEN** 不自动扩大已有角色范围或旧 Job 快照，必须按现有授权和发布流程显式配置

### Requirement: 代码知识内部新鲜度桥必须保持双身份和固定用途
内部 freshness bridge SHALL 复用现有 Knowledge 服务身份与当前 Job Knowledge Principal 的双重验证，检查目标知识库、Tool、来源配置和剩余预算。bridge MUST 只解析服务器登记的来源，调用方不得覆盖 URL、凭据或命令。SVN Secret 只在受控连接适配器内解析，不向 Knowledge MCP、Runtime、问答模型或响应返回；新鲜度查询不创建用户仓库授权。

#### Scenario: 仅持有服务身份
- **WHEN** 调用方缺少有效当前 Job 的 Knowledge Principal 或其知识库范围不匹配
- **THEN** bridge 拒绝探测，不泄露来源存在性或最新提交状态

#### Scenario: 用另一业务 MCP 凭证调用
- **WHEN** 调用方使用 ONES、文件或未知 audience 的 Principal 请求代码知识新鲜度
- **THEN** 固定身份策略拒绝，不因为共享签名信任而互通
