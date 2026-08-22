## 1. 固定已提供接口契约

- [ ] 1.1 将项目角色成员 GET 和 Team users POST 的 Method、相对 Path、Header 名称、动态值来源、请求体及成功响应整理为脱敏测试 fixture，不复制用户提供的真实 Token、人员邮箱、电话或完整现场响应。
- [ ] 1.2 将项目角色成员 GET 固定为空 JSON Body `{}`，并在请求对象和 Mock 测试中精确断言，不增加无 Body 兼容分支。
- [ ] 1.3 固定 `ones_list_project_role_members` 的输入为 `project_uuid`，输出为按角色组织的 `role_uuid`、`role_name` 和成员 `uuid`、`name`，并明确数量/长度上限。

## 2. GraphQL 文件化与工作项回归

- [ ] 2.1 创建 `services/ones_mcp_server/provider/graphql/documents/` 资源目录和简单文本加载函数，不增加 GraphQL parser、指纹或依赖索引。
- [ ] 2.2 将现有工作项搜索 document 原样移动到独立 `.graphql` 文件，并让 `WorkItemSearchOperation` 直接加载该文件。
- [ ] 2.3 增加工作项迁移回归，精确比较迁移前后的固定 Path、Query、variables、Tool schema、规范化输出和错误行为。
- [ ] 2.4 增加资源缺失/空文件和现有轻量 `query` 前缀校验测试，确保镜像漏装文件时启动失败。

## 3. 增加受限 REST HTTP 能力

- [ ] 3.1 重构 `OnesProviderHttpClient` 的公共 JSON 响应读取与错误分类，保持当前超时、响应上限、禁止重定向和禁用环境代理行为。
- [ ] 3.2 增加仅供代码 Operation 调用的固定 GET JSON 方法，使项目角色成员 Operation 发送空 JSON Body `{}`，并继续拒绝动态 URL、查询串和 fragment。
- [ ] 3.3 保持并复用固定 POST JSON 方法，使 GraphQL POST 和 Team users POST 共用传输边界但保留各自请求构造。
- [ ] 3.4 增加请求对象测试，逐项断言 GET/POST Method、固定 Path、Header、Body、超时、重定向拒绝、代理禁用、响应上限和 HTTP 状态映射。

## 4. 实现两个显式 REST Operation

- [ ] 4.1 创建项目角色成员 GET Operation，只接受代码传入的当前默认 Team UUID 和已校验 `project_uuid`，并按已提供契约构造固定 Path、Headers 和 Body。
- [ ] 4.2 为 GET Operation 实现响应解析，只保留角色 UUID/名称和 member UUID 列表，并覆盖正常、空列表、字段缺失、类型错误和响应超限测试。
- [ ] 4.3 创建 Team users POST Operation，按已提供契约提交去重后的 `uuids`，固定当前默认 Team Path 和身份 Header。
- [ ] 4.4 为 POST Operation 实现响应解析，只保留用户 UUID/姓名并丢弃邮箱、电话、头像、部门及其它额外字段，覆盖缺少用户和重复 UUID 测试。

## 5. 实现项目角色人员 Tool

- [ ] 5.1 增加 `ones_list_project_role_members` 的 Tool identifier、input/output schema、description、只读标记和精确 invoke scope。
- [ ] 5.2 实现 `ProjectRoleMemberService` 的固定两步调用：GET 角色成员、去重 UUID、POST 用户、按原角色顺序映射姓名；空成员时跳过 POST。
- [ ] 5.3 当用户查询缺少任一被引用 UUID、任一步响应不合法或第二步失败时，使整次调用失败且不返回半成品。
- [ ] 5.4 将新 Service 装配到 `OnesToolRegistry`，复用现有 Principal 解析、当前个人凭据、默认 Team、一次 Token 刷新和统一 MCP 审计。
- [ ] 5.5 更新代码 Tool Manifest 和面向 Agent 的 ONES Tool 说明，仅暴露 `project_uuid` 和业务输出，不暴露 REST 实现参数。

## 6. Mock、授权与真实环境验证

- [ ] 6.1 扩展 ONES Mock 的两个固定 REST 路由，以脱敏数据覆盖多角色共享成员、空成员和用户响应缺失场景，并精确断言收到的 Method、Path、Headers 和 Body。
- [ ] 6.2 增加 Tool 测试，覆盖输入额外字段、无 Principal、无个人凭据、无默认 Team、Tool 未冻结、Publication/Grant 缺失、401 刷新、403 和审计按实际 Tool identifier 记录。
- [ ] 6.3 扫描测试 fixture、日志和审计 payload，确认不包含真实 Token、Cookie、密码、邮箱、电话或完整 Provider 响应。
- [ ] 6.4 在用户提供的目标 ONES 环境执行一次获授权只读验证，只记录 HTTP/业务结果类别、数量、时延和 correlation ID；容器/Mock 通过不得代替该结果。

## 7. 构建、发布与收口

- [ ] 7.1 验证 `ones-mcp` 镜像包含 GraphQL `.graphql` 资源，并运行 import/resource smoke test。
- [ ] 7.2 运行 ONES Provider、GraphQL、REST Operation、Tool、Principal、审计和 Mock MCP E2E 聚焦测试，再运行完整后端测试、`docker compose config --quiet` 和 `git diff --check`。
- [ ] 7.3 创建显式包含新 Tool 的新 Agent/Application Publication、角色 Grant 和新 Job 验收数据，证明旧 Publication、Grant 和 Job 不自动获得能力。
- [ ] 7.4 验证 `QUERY_LIBRARY_LIST` 在完整 URL、Method、Headers、variables 和响应报文补齐前没有 Operation、Tool 或 Mock 路由，且实现中没有 AST、指纹、反向依赖、动态编排、FastMCP 或任意接口执行器。
- [ ] 7.5 使用严格模式验证本 OpenSpec change，并记录已确认的 Mock/真实环境证据与仍未提供契约的接口清单。
