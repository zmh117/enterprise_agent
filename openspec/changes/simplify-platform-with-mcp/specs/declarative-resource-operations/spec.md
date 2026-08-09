## ADDED Requirements

### Requirement: 资源声明文件不得包含 Secret 明文
数据库、Redis 和 Loki MUST 使用声明式 YAML 表达稳定 Resource Code、Provider、非敏感连接配置、作用域、查询限制和 `secret://platform/<code>` 引用；文件 MUST NOT 包含密码、Token、Cookie、完整认证 Header、Master Key 或可逆密文。

#### Scenario: Manifest 包含数据库密码
- **WHEN** `platformctl resource plan/apply` 读取包含 `password` 明文字段的文件
- **THEN** CLI 在发起写请求前拒绝文件并返回字段级安全错误

#### Scenario: Manifest 使用 Secret Ref
- **WHEN** 文件只包含合法 `passwordRef` 或 `authRef`
- **THEN** CLI 可以生成脱敏 diff，输出不得解析或展示 Secret 值

### Requirement: platformctl 必须通过管理 API 与统一授权操作
`platformctl` MUST 使用现有登录 Session、CSRF 和细粒度 RBAC 调用管理 API，MUST NOT 直接写数据库；本地 Session 材料 MUST 使用 `0600` 权限保存，并 MUST 不出现在命令输出、历史、日志或审计载荷中。

#### Scenario: 未授权用户发布资源
- **WHEN** 普通用户执行 `platformctl resource publish`
- **THEN** 管理 API 拒绝操作且不改变 Draft、Revision 或 Deployment

#### Scenario: CLI 发生 revision 冲突
- **WHEN** `apply` 使用过期 expected revision
- **THEN** API 返回冲突，CLI 展示安全 diff 并要求重新 plan，不静默覆盖

### Requirement: 资源必须按 Draft、验证、Revision 和 Deployment 发布
Resource MUST 保留稳定 Identity、可编辑 Draft、绑定当前内容 Hash 的技术 Verification 和不可变 Revision；`apply` MUST 默认只创建或更新 Draft，只有当前 Draft 验证通过后才能创建新 Revision 并将精确 MCP Resource Deployment 原子指向该 Revision。

#### Scenario: Apply 后未显式 Publish
- **WHEN** 管理员执行 `platformctl resource apply`
- **THEN** 运行时继续使用原 Deployment，Draft 不自动生效

#### Scenario: 发布已验证 Draft
- **WHEN** 当前 Draft 的连接、Secret、只读权限和 Provider 契约验证均通过
- **THEN** 系统创建不可变 Revision、更新精确 Deployment并记录 actor、内容 Hash 和审计

### Requirement: MCP Resource Deployment 必须唯一并可确定性冻结
每个运行环境中的 `server_code + resource_code` MUST 至多有一个活动 Deployment，并 MUST 指向一个精确 `PUBLISHED` Resource Revision；Job 和 Tool Call MUST 保存 Deployment ID 与 Resource Revision ID，禁止解析浮动 `latest` 或按列表顺序猜测。

#### Scenario: Resource 发布后创建新 Job
- **WHEN** Deployment 已从 Revision 1 原子切换到 Revision 2
- **THEN** 新 Job 冻结 Revision 2，已存在 Job 仍保留自己的精确 Revision 事实

#### Scenario: Deployment 出现多个活动 Revision
- **WHEN** 数据校验发现同一 Server/Resource 存在两个活动指针
- **THEN** Runtime 标记配置完整性失败并拒绝相关新 Tool Call

### Requirement: 取消发布必须阻止新调用但保留历史
`platformctl resource unpublish` MUST 禁用精确 Deployment 并阻止新的资源依赖 Job、Tool Call和重试；已经发送到上游的单次请求 MAY 完成，历史 Revision、Job 和审计 MUST 保留。回滚 MUST 从历史 Revision 创建新 Draft、重新验证并发布新 Revision，禁止直接恢复已禁用 Revision。

#### Scenario: 取消已使用的数据库发布
- **WHEN** 管理员取消活动数据库 Deployment
- **THEN** 新数据库 Tool Call立即失败关闭，既有历史记录仍可查询且不自动切换旧 Revision

#### Scenario: 回滚历史配置
- **WHEN** 管理员选择 Revision 1 作为回滚来源
- **THEN** 系统创建内容等价的新 Draft，只有重新验证并发布后才生成新的活动 Revision

### Requirement: Secret 必须通过 CLI 安全创建和轮换
`platformctl secret create/rotate` MUST 只从 stdin 或受保护文件描述符读取明文，管理 API MUST 在持久化前使用仓库外 Master Key 加密；资源只保存 Secret Ref。Secret 轮换 MUST 更新活动版本和 runtime generation，但在 Resource 配置与 Ref 未变化时 MUST NOT 要求重新发布 Resource Revision。

#### Scenario: 通过 stdin 创建 Secret
- **WHEN** 管理员输入数据库密码创建 Secret
- **THEN** CLI、API 响应、日志和审计只返回 code、ref、版本和脱敏摘要，不返回明文

#### Scenario: 轮换被活动资源引用的 Secret
- **WHEN** Secret 新版本激活且 Resource Ref 未变化
- **THEN** Runtime 构建新 generation并刷新连接，Resource Revision ID 保持不变

### Requirement: Runtime generation 必须原子切换并保持精确 LKG
Data MCP MUST 根据活动 Deployment、Resource Revision 和 Secret active version 完整构建不可变 generation 后原子切换；构建失败 MAY 对同一 Resource Revision 保留精确 Last Known Good，但 MUST NOT 把 Job 浮动到其他 Revision。

#### Scenario: 新 Secret 版本无法建立连接
- **WHEN** Runtime 不能使用新活动 Secret 构建连接且存在相同 Resource Revision 的 LKG
- **THEN** 资源进入 degraded 并继续使用该精确 Revision 的 LKG，同时输出脱敏错误

#### Scenario: 精确 Revision 没有 LKG
- **WHEN** Job 冻结的 Resource Revision 从未成功加载
- **THEN** Data MCP 拒绝 Tool Call而不是使用其他历史 Revision

### Requirement: 配置和发布操作不得成为 MCP Tool
Resource、Secret、Deployment、破坏性切换检查和 Server 管理命令 MUST 只存在于受认证控制 API/CLI，MUST NOT 出现在任何模型可见 `tools/list` 中。

#### Scenario: Agent 请求取消资源发布
- **WHEN** 模型尝试调用或构造 `resource_publish`、`resource_unpublish` 或 `secret_rotate`
- **THEN** MCP 目录不存在这些 Tool，服务端也拒绝任何对应协议调用
