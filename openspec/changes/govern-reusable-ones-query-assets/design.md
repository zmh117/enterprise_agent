## Context

当前 `ones-mcp` 使用官方 `mcp==2.0.0`，只暴露 `ones_work_item_search`。Provider 层只有 `post_json()` 和一个轻量 `GraphqlOperationRegistry`；工作项 GraphQL document 直接写在 Python 中。用户后续会逐个提供 ONES 接口的 URL、Method、Headers、请求报文和响应报文，其中已经提供项目角色人员 REST GET 以及按 UUID 查询用户的 REST POST。

本 change 不建设接口配置平台。每个接口都是代码拥有的固定 Operation，每个业务 Tool 都在 Service 中写明调用哪些 Operation、按什么固定顺序调用。现有 Principal JWT、个人 ONES 身份、默认 Team、Token 刷新、审计和发布授权继续复用。

## Goals / Non-Goals

**Goals:**

- GraphQL document 放入独立目录，由对应 Operation 直接读取。
- REST GET、REST POST 和 GraphQL POST 都能按用户提供的完整报文逐个实现。
- 新增项目角色人员 Tool：查询角色成员 UUID，再批量查询姓名并按角色返回。
- 保持工作项搜索行为不变，并保留现有身份、授权、Token 刷新和审计。
- 没有完整接口报文时不猜 URL、变量、Header 或响应结构。

**Non-Goals:**

- 不增加 AST 解析、GraphQL document 指纹、Query 到 Tool 的反向依赖索引。
- 不增加模型选择 Query、运行时组合接口或数据库配置接口的动态编排。
- 不增加任意 URL、Method、Header、请求体或 GraphQL 执行 Tool。
- 不迁移 FastMCP，不改变 Streamable HTTP 和独立 `ones-mcp` 进程。
- 不在本 change 放宽生产 HTTPS、Provider Host allowlist、当前用户或默认 Team 边界。
- 不实现尚未获得完整 URL、Method、Headers、变量和响应样例的 `QUERY_LIBRARY_LIST` Tool。

## Decisions

### 1. 每个 Provider 接口使用一个显式 Operation

GraphQL Operation 继续包含稳定 code、固定 Path、变量构造和响应解析，只把 document 改为从 `provider/graphql/documents/` 读取。REST Operation 放在 `provider/rest/operations/`，明确写出 Method、Path 模板、固定 Header、请求体构造和响应解析。

Operation 不从 MCP 输入接收 URL、Method、Header 或原始请求体。新增接口时只按用户提供的完整契约增加一个 Operation 和对应测试。替代方案是通用接口定义/动态执行器，但它会扩大输入面且不符合“给什么接口写什么接口”的要求，因此不采用。

### 2. HTTP Client 只增加必要的 GET/POST JSON 发送能力

在现有 `OnesProviderHttpClient` 内复用超时、响应上限、禁止重定向、禁用环境代理、HTTP 状态分类和 JSON 解析。Client 增加受内部 Operation 调用的 GET/POST JSON 方法；Method 只允许 `GET`、`POST`，Path 必须是代码固定的相对路径。

项目角色成员 GET 按用户已提供的报文发送固定空 JSON Body `{}`。其它 GET 是否包含 Body 只按各自后续报文决定，不从本接口推广。固定 `Referer`、`cache-control`、`Content-Type` 等 Header 按接口契约构造，`Ones-Auth-Token` 和 `Ones-User-Id` 的值始终来自当前 Principal 身份链，不复制用户示例中的值。

### 3. 项目角色人员 Tool 使用固定两步调用

新增 `ones_list_project_role_members`，模型只传 `project_uuid`：

```text
当前 Principal 默认 Team + project_uuid
  -> GET role_members
  -> 收集并去重所有 member UUID
  -> POST users {uuids: [...]}
  -> 按原角色顺序组装 [{role_uuid, role_name, members:[{uuid, name}]}]
```

这段顺序直接写在 `ProjectRoleMemberService` 中，不建立流程 DSL。GET 返回的角色和成员 UUID、POST 返回的用户 UUID/姓名都必须符合用户提供的响应结构；用户查询缺少被请求 UUID 时整次调用按 Provider 响应不完整失败，不静默丢人或跨角色错配。

### 4. 一个 GraphQL 文件被多个 Tool 使用时直接引用

一个 `.graphql` 文件可以由多个 Python Operation/Service 直接加载，无需维护反向依赖表。一个 Tool 需要多个接口时，由其 Service 按固定代码顺序调用；模型不能改变接口集合和顺序。

Registry 继续做当前已有的 code 唯一、固定 GraphQL Path 和 document 以 `query` 开头的轻量检查。当前规模下不增加 GraphQL parser 依赖。

### 5. 完整接口契约是新增 Operation 的前置条件

实现一个新接口前必须具有：固定 URL/Path、Method、Headers 名称与固定值/动态值来源、请求体或 Query variables、成功响应样例、空结果样例和主要错误状态。缺少任一影响代码行为的字段时停止该接口实现并向用户确认，不从其它 ONES 接口推断。

当前 `QUERY_LIBRARY_LIST` 缺少固定 endpoint、完整变量声明/JSON 和响应报文，因此本 change 只保留其文件化方向，不注册 Operation 或 Tool。

### 6. 沿用现有发布和安全边界

新 Tool 继续要求 Principal JWT、精确 Tool invoke scope、当前用户的活动 ONES Token/User ID、默认 Team、Agent/Application Publication、角色 Grant 和 Job 冻结 Tool/schema hash。新代码不会扩大旧 Publication 或旧 Job。

Provider 原始响应只在内存中解析；Tool 输出只包含角色 UUID/名称和成员 UUID/姓名。日志、审计、fixture 和文档不得保存用户提供的真实 Token、Cookie、密码、邮箱、电话或完整人员响应。

## Risks / Trade-offs

- [用户提供接口与目标 ONES 版本不一致] → 每个 Operation 使用对应接口的脱敏 Mock fixture；失败只修该 Operation，不抽象成通用兼容层。
- [GET Body 在不同网关行为不同] → 项目角色成员接口严格发送用户提供的固定空 JSON Body，并通过测试断言 Method、Body 和 Header；其它 GET 另按各自报文实现。
- [两步请求中第二步失败] → 整次 Tool 失败并保留同一 correlation ID，不返回只有 UUID 的半成品。
- [人员数据进入模型或日志过多] → Tool 只返回角色与 UUID/姓名，限制角色数、每角色人数和字符串长度，不返回邮箱、电话或原始响应。
- [真实 ONES 只提供 HTTP] → local/test 可使用现有显式 insecure 配置；生产仍要求 HTTPS。是否放宽生产 HTTP 必须另行提出安全变更。
- [直接引用同一 GraphQL 文件无法自动列出影响 Tool] → 依靠代码搜索和相关 Tool 测试；当前规模接受该维护成本。

## Migration Plan

1. 增加 GraphQL documents 目录和简单资源读取，将工作项 document 原样迁移并运行现有回归。
2. 扩展 HTTP Client 的固定 GET/POST JSON 能力，并用请求对象测试精确断言 Method、Path、Headers 和 Body。
3. 增加项目角色成员 GET Operation、用户查询 POST Operation及脱敏 Mock 响应解析测试。
4. 增加 `ProjectRoleMemberService`、`ones_list_project_role_members` Manifest/Registry 装配和身份、授权、刷新、审计测试。
5. 构建 `ones-mcp` 与 ONES Mock，执行工作项回归和新 Tool 的确定性 MCP E2E。
6. 新建显式包含新 Tool 的 Publication、Grant 和 Job；旧快照保持不变。

回滚时恢复上一版 `ones-mcp` 镜像并停用包含新 Tool 的新 Publication/Job。工作项 Tool 的 identifier/schema 不变，不需要改写历史快照。

## Open Questions

- 项目成员数量超过用户查询接口单次 UUID 上限时，ONES 是否要求分批；用户未提供上限前不自行设计分页。
- `QUERY_LIBRARY_LIST` 的完整 URL、Method、Headers、变量声明/JSON、空结果和成功响应报文仍待用户提供。
