## Why

当前 `ones-mcp` 只实现了固定 GraphQL POST，GraphQL document 以内联字符串保存在 Python 中，也不能调用用户已经提供的 REST GET/POST 接口。需要按用户提供的 URL、Method、Headers、请求报文和响应报文逐个实现只读 ONES Tool，同时避免引入通用 Query 平台或动态接口执行能力。

## What Changes

- 在 `services/ones_mcp_server/provider/graphql/documents/` 存放 GraphQL 文件；每个 GraphQL Operation 直接引用自己的文件，一个文件可以被多个 Tool 直接引用。
- 保留当前轻量 `GraphqlOperationRegistry`，只登记代码明确引用的 Operation；不增加 AST 校验、document 指纹、反向依赖索引或动态编排。
- 扩展现有受限 HTTP Client，使代码拥有的 Operation 可以按用户提供的契约发送固定 REST GET、REST POST 或 GraphQL POST；Method、Path、固定 Header 和请求体形状都写在对应 Operation 中。
- 保留当前 Principal JWT、当前用户 ONES Token/User ID、默认 Team、Token 刷新、超时、响应大小、错误映射和统一 MCP 审计；Token 等动态认证值由现有身份链注入，不写进代码或 GraphQL 文件。
- 将现有工作项搜索 GraphQL document 移入目录，保持 `ones_work_item_search` 的 Tool 契约和调用行为不变。
- 按已提供的接口增加项目角色人员查询：先调用固定 `GET .../team/{team_uuid}/project/{project_uuid}/role_members`，再将返回的成员 UUID 去重后调用固定 `POST .../team/{team_uuid}/users`，由新 Tool `ones_list_project_role_members` 返回角色及成员 UUID/姓名。
- `QUERY_LIBRARY_LIST` 仅在用户补齐 GraphQL URL、Method、Headers、完整变量声明/请求体和响应样例后实现；当前 change 不猜测 `$pagination` 类型或 Provider Path。
- ONES Mock 和测试只覆盖已经获得完整接口契约的 Operation；不得从一个接口推断其它 ONES 接口。
- 保留官方 `mcp==2.0.0`、Streamable HTTP 和独立 `ones-mcp` 进程；不迁移 FastMCP，不增加任意 URL/Method/Header/GraphQL Tool，也不增加写接口或跨 Team 查询。

## Capabilities

### New Capabilities

- `ones-explicit-provider-interfaces`: 定义由代码逐个实现的 ONES REST/GraphQL 只读接口、GraphQL 文件存放方式和受限 HTTP 调用边界。

### Modified Capabilities

- `governed-api-capability`: 新增按当前用户默认 Team 查询项目角色人员的显式只读 MCP Tool，同时保留现有身份、发布、授权、审计和失败关闭边界。

## Impact

- 影响 `services/ones_mcp_server/provider/http_client.py`、`provider/graphql/`、新增的 `provider/rest/`、`tools/`、启动装配、Tool Manifest、ONES Mock 和相关后端测试。
- 新 Tool 需要新的 Tool Manifest 条目、Agent/Application Publication、角色 Grant 和新 Job 显式选择；旧 Publication 和旧 Job 不自动获得该 Tool。
- 不新增数据库动态接口定义，不允许模型或管理端提交 URL、Method、Header、请求体模板或 GraphQL 文本。
- 不保存或记录用户提供报文中的真实 Token、Cookie、密码、人员邮箱、电话或完整 Provider 响应；测试只使用合成或脱敏数据。
- 生产环境仍遵守现有 HTTPS 和 Provider Host allowlist 规范；用户提供的 HTTP 内网 URL 只可在当前规范允许的 local/test 环境使用，生产 HTTP 例外不属于本 change。
