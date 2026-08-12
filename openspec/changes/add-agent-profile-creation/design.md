## Context

当前 `agent_definition` 已支持 `python-v1` 与 `typescript-v1`，但 Agent 配置 API 只有查询、草稿、校验、发布和回滚，没有创建入口；前端列表为空时只渲染空网格。两个固定 Agent 仅存在于可选的 `local_seed.sql`，Compose migrator 在空库启动时只执行 migration、管理员 bootstrap 和 Runtime grant，因此恢复后的数据库可以合法到达 schema head 却没有 Agent。

现有 migration catalog 在 `103_contract_retire_compatibility_shadows.sql` 处进入 staged schema contract，正常 migration 不能越过该 contract 新增 `104`。本变更不改变表结构，默认 Agent 应通过独立、幂等的应用 bootstrap 完成，而不是修改 migration ledger 或把本地完整示例 seed 引入部署。

## Goals / Non-Goals

**Goals:**

- 空库启动后稳定存在固定 Python 与 TypeScript Agent 定义及可编辑初始 Draft。
- 允许具备 Agent 全局编辑权限的管理员创建业务 Agent，并选择不可变 Runtime kind。
- 创建定义与初始 Draft 原子提交，重复 code 和并发创建确定性失败。
- 前端在空列表时提供可操作空状态，并在创建成功后进入详情配置。
- 复用既有草稿校验、发布、模型连接、审计和 RBAC 边界。

**Non-Goals:**

- 不支持删除、复制、归档或修改 Agent code/Runtime kind。
- 不为新 Agent 自动创建模型凭据、Publication、业务应用绑定、Channel 绑定或运行路由。
- 不改变 Python/TypeScript Runtime 实现、模型连接协议或现有 Job 快照语义。
- 不运行包含示例连接器、示例权限和示例业务数据的完整 `local_seed.sql`。

## Decisions

### 1. 使用独立 bootstrap 命令初始化固定 Agent

新增 `bootstrap_agents` CLI，并在 Compose migrator 的管理员 bootstrap 之后、Runtime grant 之前运行。命令要求 schema head 当前有效，使用确定性 code 检查两个固定 Agent：不存在时创建 Definition 与 r1 Draft；已存在时不覆盖名称、配置、Publication 或用户修改；若同一固定 code 的 Runtime kind 不匹配则失败关闭。

选择应用 bootstrap 而非新 migration，是因为本变更没有 schema 变化，且当前 catalog 不允许在 staged contract 后追加普通 migration。选择 Definition + Draft 而非完整本地 seed，是为了不把示例 Connector、Publication 或业务数据带入恢复后的部署。

### 2. 创建 API 复用 `agents.edit` 全局能力

新增 `POST /api/admin/agents`。由于待创建资源尚不存在，Controller 与 Service 都以 `resource_type=agent`、`resource_code=*`、`action=edit` 校验既有 `agents.edit` 能力，并继续执行 CSRF 校验。列表响应增加 `permissions.can_create`，前端据此显示创建入口。

不新增 `agents.create` 能力，避免为同一管理边界引入第二套授权含义；现有 capability 已将 Agent 编辑定义为可分配的中风险管理权限。

### 3. Agent code 与 Runtime 在创建边界固定

请求字段为 `code`、`name`、`description`、`project_code`、`runtime_kind`。code 使用小写 kebab-case，唯一且创建后不可变；Runtime 只允许 `python-v1` 或 `typescript-v1`；用户创建的 Definition classification 固定为 `business`、status 固定为 `enabled`。

服务层不接受客户端提交 classification、status、current publication、revision、Draft config 或 created_by，防止越权设置平台状态。

### 4. 创建时原子生成安全初始 Draft

Repository 在同一 unit of work 中插入 Definition 与 r1 Draft。初始 Draft 使用平台固定模板：空业务指令、名称作为业务角色、当前项目范围、默认执行限制、空 Skill/Tool/Channel 列表，以及平台默认的非敏感模型选择。管理 API 创建时若默认模型连接已初始化则引用其当前 revision；deployment bootstrap 早于 API 模型连接初始化时保留空 revision 引用，进入详情并保存后再按既有流程固定连接。创建不触发 validate/publish，也不设置 `current_publication_id`。

数据库唯一约束是并发冲突的最终裁决；Service 将冲突投影为稳定 `agent_code_conflict`（HTTP 409），不暴露 SQL 或内部异常。

### 5. 列表内联创建面板而非路由级向导

Agent 列表页提供“新建 Agent”按钮，展开受控创建面板。字段包含编码、名称、描述、项目编码和 Runtime 单选；页面展示 code/Runtime 不可修改及“不会自动发布”的提示。成功后刷新列表并导航至 `/agent-profiles/{code}`；失败保留输入并显示结构化错误。空列表时展示同一个创建入口，而不是空网格。

## Risks / Trade-offs

- [多个 migrator 实例并发执行 bootstrap] → 依赖 code 唯一约束与冲突后重读，命令保持幂等；Runtime 不一致则失败关闭。
- [固定 Agent 已被用户配置] → bootstrap 只补缺失 Definition/Draft，不覆盖已有 Draft 或 Publication。
- [初始 Draft 尚未具备可发布模型凭据] → 创建仍成功，详情页明确显示模型连接状态；发布继续走既有校验并失败关闭。
- [旧客户端只识别列表数组] → API 保留 `agents` 字段，仅以附加字段返回权限；现有客户端不受破坏。
- [本地完整 seed 与 bootstrap 固定记录并存] → bootstrap 使用稳定 fixed code 并只在缺失时创建；测试 seed 流程继续独立验证，不在生产恢复中执行。

## Migration Plan

1. 部署包含创建 API、bootstrap CLI 与前端的新版本。
2. 重建并运行 migrator；管理员 bootstrap 完成后幂等补齐两个固定 Agent。
3. 启动 API/Worker/前端，验证列表展示两个未发布或既有状态的 Agent。
4. 验证创建 Python 与 TypeScript Agent 均得到 r1 Draft，且没有 Publication 或业务应用引用。
5. 回滚应用版本时保留已创建 Definition/Draft；旧版本仍可读取这些通用表记录。无需回滚数据或 migration ledger。

## Open Questions

无。用户已确认采用“预置两个默认 Agent，同时允许用户新建”的方案。
