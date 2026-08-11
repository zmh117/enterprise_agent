# Enterprise Agent 当前上下文

本文件只描述当前领域语言和系统边界。历史 API Platform 术语与决策位于 `docs/archive/legacy-api-platform/`，不得覆盖当前代码、主 OpenSpec 或活动变更。

## 核心领域语言

**内部用户（Internal User）**

平台中承载角色、业务应用权限和数据范围的人员主体。钉钉或 ONES 用户都是外部身份，不直接成为授权主体。

**外部身份绑定（External Identity Binding）**

内部用户与受信外部系统账号的已验证关联。它只证明主体对应关系，不保存可重复使用的登录凭据，也不自动授予业务应用或工具权限。

**ONES 身份验证证明（ONES Identity Verification Proof）**

当前用户在一次请求中临时提交的邮箱、密码和登录响应 Token。请求结束前必须丢弃；数据库只保留 ONES User ID、显示名称、已验证 Team、默认 Team 和验证时间。

**Agent Definition / Revision / Publication**

Agent 的稳定身份、追加式草稿和不可变发布。Definition 创建后固定 `python-v1` 或 `typescript-v1`；Publication 冻结模型连接、指令、Skill、执行策略、Runtime kind 和 MCP Tool Envelope。

**Business Application Publication**

业务应用的不可变运行装配，冻结 Agent Publication、可选 Workflow、Trigger、Delivery、会话/执行策略和 Agent MCP Tool Envelope 的显式子集。

**MCP Tool Manifest**

由代码发布的固定只读工具目录，包含稳定 tool identifier、模型描述、输入 Schema、只读语义和资源类型。管理端不能创建动态 Handler、任意 URL、SQL 模板、脚本、Shell 或通用 MCP Server。

**Tool Resource**

数据库、Redis 或 Loki 等受治理资源身份。连接内容通过 Draft、验证和不可变 Revision 发布；Secret 只以 `secret_ref` 引用，运行时不读取草稿。

**业务数据范围（Business Data Scope）**

角色在业务应用内获得的明确 environment、可选 base 和 workshop 集合。用户消息可以不完整或变化；Agent 根据消息和 Skill 选择 Tool Call 参数，服务端在每次调用时实时复核授权范围和唯一资源。

**Agent Job**

一次异步执行请求。Job 冻结用户主体、应用/Agent Publication、Runtime kind、MCP Tool Schema 与授权摘要，但不把某次自然语言推断出的 environment/base/workshop 固化为不可变路由目标。

**Schema Baseline Generation**

当前 schema 从 `100_baseline_v1.sql` 开始。空库执行 `100[,101...]`；精确 legacy 042 数据库通过不可变 manifest 验证后只登记等价 marker，形成 `001..042,100[,101...]`。

## 当前运行链

```text
DingTalk / Webhook / Debug
  -> API Control Plane + PostgreSQL + RabbitMQ
  -> Agent Worker
  -> Python Runtime or TypeScript Runtime
  -> tool-mcp
  -> Published Resource Revision + Secret Ref
  -> Job / Tool Call / Delivery / Audit
```

Worker 负责可靠调度和 Runtime 选择，不内嵌模型 SDK 或工具实现。两个 Runtime 分别安装对应 Claude Agent SDK 并执行模型循环。`tool-mcp` 是标准 MCP Server，负责工具 Schema、实时身份/RBAC/应用/数据范围复核、资源解析和有界只读适配器调用。

## 治理边界

- 保留：统一身份、RBAC、业务应用授权、Agent/Application Publication、Resource、Secret、审计、Job/Delivery 历史。
- 退役：API Capability、Handler、API Connection、Application Resource Mapping、Internal API Platform、个人 API 调用 Token、旧 Runtime Tool MCP 与 HS256 signing key。
- MCP 不新增独立 Token、JWT、RBAC 或复杂治理层；它替换工具传输协议，不替代平台现有治理。
- ONES 身份绑定独立于 MCP。未来 ONES MCP 调用凭据必须另行设计，不能复用一次性登录材料。
- 工具只读且固定，不提供任意网络、文件写入、Shell、脚本或通用执行器。

## 当前事实入口

- 项目和运行边界：[README.md](README.md)
- 文档事实层级：[docs/README.md](docs/README.md)
- OpenSpec 主规格：`openspec/specs/`
- 活动实现变更：`openspec/changes/`
- 活动 schema：[backend/migrations/README.md](backend/migrations/README.md)

讨论新设计时必须区分“当前实现”“活动规范目标”“日期化验收”和“历史归档”。
