# 治理前端恢复清单

## 盘点口径

- 事实源：当前 `frontend/src`、只作参考的 `bak/frontend/src`、当前 FastAPI 路由与本 change 的 delta specs。
- 复用仅限布局、表格、表单、对话框、中文状态表达和可访问性交互；领域类型、API Client、Query Key、mutation、权限判断与错误处理必须按当前 API 重写。
- `bak/frontend` 永远不是生产依赖，构建产物不得引用备份目录、静态业务 fixture 或退役 API。
- 登录、Session、CSRF、对象范围、审计、幂等、revision/version 冲突和敏感字段脱敏属于恢复范围，不因 MCP 替换传输协议而删除。

## 逐页面清单

| 页面/入口 | 当前前端 | `bak/frontend` 可复用展示 | 必须重写/补齐 | 结论 |
| --- | --- | --- | --- | --- |
| 登录与账户安全 | 已实现登录 Gate、会话与改密 | Shell 中账户菜单的展示模式 | 保留当前 Session/CSRF Client；补管理路由权限 Gate | 保留当前实现 |
| Dashboard | 缺失 | `overview` 的卡片、链路布局 | 禁止 `mocks/dashboard.ts`；接入范围过滤的真实聚合 API 和 MCP 数据链路 | 重写数据层后恢复 |
| Agent 列表/详情 | 已有真实 API 工作区 | 备份的表单分区和状态展示可参考 | 补齐多 Agent、历史/回退、冲突处理与权限 Gate | 以当前实现为主 |
| Application 列表/详情 | 已有真实 API 工作区 | 备份的列表、环境状态展示可参考 | 补历史/回退、激活/停用确认、作用域权限 | 以当前实现为主 |
| 渠道与触发器 | 当前缺失 | `managed-channels` 的列表、编辑表单、测试/启停确认 | 接入当前受信 Connector API；凭据改为安全 Credential ID 选择；禁止动态 adapter/Header/template | 重写数据层后恢复 |
| Job/Session 历史 | 仅本人历史已实现 | 备份的运行状态、时间线布局 | 增加管理员范围过滤视图、Step/MCP Tool Call/Delivery、可取消状态 | 扩展当前实现 |
| 发起调试 | 退役页占位 | `debug-job-page` 的表单和结果布局 | DTO 必须由服务端固定主体、Publication、资源、Tool 上限和投递目标 | 重写数据层后恢复 |
| 用户目录/详情 | 退役页占位 | `users` 的表格、筛选、详情分区和 Dialog | 接入统一 `app_user` API；补启停、Session 撤销、角色与身份安全摘要 | 重写数据层后恢复 |
| 角色与授权 | 退役页占位 | `authorization` 的列表、授权区、成员编辑 | 删除 API Capability 字段；改为管理权限、Application 使用、数据范围和有效权限模拟 | 重写领域与数据层后恢复 |
| 未绑定钉钉身份 | 退役页占位 | `dingtalk-identity-discovery` 的筛选、候选、绑定向导 | 接入可信观测事实；禁止管理员提交任意 subject；支持新建/选择人员和初始角色 | 重写数据层后恢复 |
| 我的外部身份 | 已实现 ONES 两阶段验证和钉钉绑定入口 | 备份的身份卡片展示可参考 | 保留一次性密码边界；补管理员只读/撤销治理入口 | 保留并扩展 |
| MCP Server | 缺失 | `builtin-tools` 的目录卡片/状态 Badge 可参考 | 只读受信注册表、受控健康检查；禁止 URL/Transport/Header/Auth CRUD | 新 MCP 页面 |
| MCP Tool Publication | 缺失 | `builtin-tools` 的表格、详情 Sheet 可参考 | 接入服务端发现快照、启停/发布/回退与精确 Resource Deployment 绑定 | 新 MCP 页面 |
| Database/Redis/Loki Resource | 缺失 | `tool-resources` 的表格、表单和影响确认可参考 | 服务端拥有表单 Schema；Web 仅展示启用/停用主状态；内部保留 Draft/Revision/Deployment/Generation/LKG | 新 MCP 页面 |
| Credential Center | 缺失 | `credential-center` 的列表、轮换/停用对话框可参考 | 仅使用安全 Credential ID；浏览器 DTO 禁止 Secret Ref/Value/Ciphertext/nonce/tag/Master Key | 新 MCP 页面 |
| Model Connection | 已位于 Agent 工作区 | 无需从旧 API Connection 页面复用 | 保留模型专用受控配置；名称和路由不得与已退役通用 API Connection 混淆 | 保留当前实现 |

## 永久排除清单

以下内容既不恢复页面，也不恢复 API Client、领域类型、Query Key、fixture、路由或导航：

- `contexts/api-capabilities/**`
- API Capability、API Handler、通用 API Connection 与它们的 Release/Revision 管理界面
- Resource Mapping、字段映射、规则映射、SQL/查询模板编辑器
- Internal API Platform、Local Internal API Platform 与通用 URL/HTTP 执行器
- `mocks/dashboard.ts` 及任何静态业务成功数据
- 备份版 `shared/api/api-client.ts` 和所有指向退役 `/api/admin/api-*`、`/api/platform/builtin-*` 的调用
- 从生产源码导入 `bak/frontend`，或在构建时把备份目录作为 alias/root

## 当前后端缺口

- Agent、Application、本人历史、本人身份、Credential、MCP Resource/Tool Publication、MCP Server 状态已有当前 API，可作为首批真实数据源。
- Managed Channel 的服务和控制器存在，但管理 Router 尚未挂入主应用。
- 用户目录、角色授权、身份候选、管理员 Job/Debug 与 Dashboard 仍需恢复安全 API；不得用前端直连数据库或静态 fixture 绕过。
- Credential 当前公共 DTO 仍含可复制 `secret_ref`，必须先收紧为浏览器安全标识，再提供给 Resource/Connector 表单。

