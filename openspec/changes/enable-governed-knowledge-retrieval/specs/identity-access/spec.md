## MODIFIED Requirements

### Requirement: 平台 Principal 按 MCP 认证模式隔离
代码固定的 MCP Server policy SHALL 分别声明 `tool-mcp` 的 Job-context、`ones-mcp`、`dingtalk-mcp` 与 `knowledge-mcp` 的 Business Principal JWT、`file-service` 的 File Principal JWT。系统 MUST NOT 运行时注册任意认证模式、将一种凭证用于另一 Server 或以旧 Internal API Bearer 作为工具授权替代。

#### Scenario: tool-mcp 接收调用
- **WHEN** 请求具有完整 Job-context Header
- **THEN** 服务读取持久化 RUNNING Job，并逐项核对 invocation、内部用户、project、Session/Publication 适用事实、correlation、Runtime 协议与快照；Header 只供一致性检查，不授予权限

#### Scenario: Job-context 缺失或伪造
- **WHEN** Job 不存在、不在 RUNNING、Runtime 不兼容或任一必需 Header 与持久化事实冲突
- **THEN** 在列出或执行 Tool 前拒绝，不进入旧 Token/Handler/Capability 兼容路径

#### Scenario: 知识与 ONES audience 混用
- **WHEN** Knowledge Principal 直接调用 ONES MCP，或 ONES Principal 调用知识 MCP
- **THEN** 对应 Server 拒绝，不因两者属于同一用户或 Job 而允许跨 audience 使用

## ADDED Requirements

### Requirement: 知识库范围必须进入现有角色业务授权事实源
知识库权限 SHALL 以明确 knowledge_base_id 进入角色业务访问记录、业务 revision、预览、委派上限、原子保存、显式拒绝和 authorization hash。应用内 Tool 与 KB 范围 MUST 在同一条允许的角色访问记录中共同满足，不得跨角色拼接；直接 Agent 也 MUST 具有明确 KB 范围而非仅依赖项目 use grant。平台管理能力、知识入库和索引存在 MUST NOT 自动授予业务读取。角色 MUST NOT 授予物理 Resource Revision、Qdrant collection 或以 environment/placement 代替 KB。

#### Scenario: 分别拥有 Tool 和 KB
- **WHEN** 角色 A 只有知识检索 Tool，角色 B 只有 KB 范围，且没有一条记录同时满足
- **THEN** 当前用户不能检索该 KB，目录也不把它显示为可检索

#### Scenario: 当前全部知识库授权
- **WHEN** 管理员选择当前全部可授予知识库并保存
- **THEN** 系统展开当时明确 ID，在同一业务授权事务保存；未来新增 KB 不自动加入

#### Scenario: 并发授权修改
- **WHEN** 业务 revision 已变化或提交的 KB 超过操作者委派范围
- **THEN** 保存整体拒绝，不部分写入 KB grant，不覆盖其他授权分区

### Requirement: 知识命中必须通过当前双重权限
知识 MCP MUST 在候选上游访问前校验当前平台授权，在任何命中引用返回前同时满足 KB 角色授权和当前 Job 发起人的 ONES 工作项可读权限。平台检查 MUST 包含有效用户、适用应用/直接 Agent 授权、精确 Snapshot、来源匹配及当前资源状态；ONES 检查 MUST 使用本人唯一启用绑定和默认 Team。拒绝或未知权限的工作项 MUST NOT 通过缓存数据、共享账号、管理员账号或历史允许结果返回。

#### Scenario: 有 KB grant 但无 ONES 权限
- **WHEN** 用户获准调用知识 Tool 且 KB 范围有效，但 ONES 不允许读取候选工作项
- **THEN** 系统不返回该工作项的任何命中引用或正文

#### Scenario: ONES 可读但无 KB grant
- **WHEN** 用户本人可以读取 ONES 工作项，但平台未授予此 KB
- **THEN** 系统在向量/知识内容检索前拒绝，不因 Provider 可读而扩大平台范围

#### Scenario: 查询期间撤销授权
- **WHEN** Token 未过期但用户停用、角色成员、应用/Tool/KB grant 或来源状态已撤销
- **THEN** 返回前复核拒绝本次结果；下次调用不得复用上次允许事实

### Requirement: ONES 可读性桥必须限定同一 Job 和固定只读用途
系统 SHALL 提供仅供 knowledge-mcp 使用的固定内部可读性桥。入口 MUST 同时验证代码固定的知识服务身份和有效 Knowledge Principal，重新核对同一 RUNNING Job、用户、Publication、精确 Tool 合同、当前 KB/详情 Tool grant 及候选成员关系。服务身份 MUST 只授权访问该内部入口，不授予业务数据权限。身份服务 MUST 保持现有完整 scope 的 ONES Principal 签发/校验规则，Token 仅在平台桥内存中用于固定 ONES 可读性入口，不返回知识服务或模型。

该桥 MUST NOT 接受调用者指定 actor、server、scope、Team、URL、operation、Provider 凭据或任意工作项 UUID，MUST NOT 转为通用 MCP/HTTP 代理。私钥和 ONES 凭据 MUST NOT 分发到知识服务；固定服务凭据 MUST 与其他服务隔离，仅启用知识组件时配置。

#### Scenario: 合法候选校验
- **WHEN** 受信知识服务为有效 Job 提交属于本次 KB/索引的内部文档引用
- **THEN** 平台从持久化事实解析 ONES 目标，签发并内部使用该 Job 自身 ONES Principal，只请求固定只读投影

#### Scenario: 服务身份尝试替用户授权
- **WHEN** 服务凭据有效但 Knowledge Principal、详情 Tool grant、候选归属或当前用户状态无效
- **THEN** 平台在 ONES 请求前拒绝，不以服务权限补全用户权限

#### Scenario: 内部入口尝试提权
- **WHEN** 请求试图更换用户、扩大 scope、指定任意 Provider 地址或调用 mutation
- **THEN** 严格入口合同拒绝且只记录安全失败码，不能取得 ONES Token 或正文
