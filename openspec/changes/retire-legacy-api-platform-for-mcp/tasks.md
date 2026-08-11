## 1. 迁移前事实与保护门禁

- [x] 1.1 盘点并记录 Capability、API Connection、Resource Mapping、Internal API 配置、活动发布和在途 Job 的当前引用路径
- [x] 1.2 为破坏性迁移增加活动旧引用检查和数据库备份前置说明
- [x] 1.3 增加残留扫描测试，禁止 `runtime-tool-mcp`、HS256 issuer/verifier/signing key、`RUNTIME_TOOL_MCP_*` 和 Internal API Platform 配置回归

## 2. 标准 MCP Tool 直接运行时

- [x] 2.1 将内置工具代码 Registry 收敛为 MCP Tool Manifest，去除 Handler Version/Release 运行依赖
- [x] 2.2 实现基于 Job Tool、调用参数与当前 Role scope 的唯一工具资源解析器，覆盖 environment/base/workshop/placement 零命中和多命中
- [x] 2.3 将数据库只读 SQL、schema directory、Redis 与 Loki 执行能力内聚到 `tool-mcp`
- [x] 2.4 让 `tool-mcp` 直接解析 Resource Revision 与平台 Secret，并移除 GovernedApiRuntimeExecutor/InternalApiClient 依赖
- [x] 2.5 更新 Tool MCP schema、错误分类、结果 envelope 和审计，确保不记录 Secret/Prompt/无界响应
- [x] 2.6 更新 Python/TypeScript Runtime 合约，只传固定 Server code 和精确 Tool identifier/schema hash
- [x] 2.7 增加双 Runtime 等价工具调用、撤权、schema drift、资源歧义和只读拒绝测试

## 3. Agent Application Job 与角色模型

- [x] 3.1 从 Agent Draft/Publication/API/UI 删除 API Capability Envelope 与 Built-in Tool Release 字段，改为 MCP Tool identifier/schema hash
- [x] 3.2 从 Application Draft/Publication/API/UI 删除 Capability Allowlist、Resource Mapping、资源矩阵和旧解析表
- [x] 3.3 保留 Application MCP Tool 显式子集并校验其属于所选 Agent Publication Envelope
- [x] 3.4 调整 Job 创建和快照，只冻结 MCP Tool 与发布/授权摘要；不得冻结或强制覆盖调用时 environment/base/workshop/placement
- [x] 3.5 调整角色授权/有效权限预览，只保留应用访问、MCP Tool 使用权限和业务数据范围
- [x] 3.6 更新 DingTalk→Application→Agent→Job 链路，确保 Routing Context 不充当工具目标快照、普通问候不解析资源、只有实际工具调用才由 Skill 选择目标并实时鉴权

## 4. 永久删除旧 API Capability 平台

- [x] 4.1 删除 `api_capability` 后端模块、Bootstrap 装配、管理 routes 和运行时执行器
- [x] 4.2 删除 API Capability/Handler/API Connection 前端页面、路由、请求模型和导航权限
- [x] 4.3 删除 Agent/Application/Job/身份模块对 Capability Release、Handler、API Connection 和 Mapping Plan 的依赖
- [x] 4.4 删除仅服务于旧 API Capability 的 ONES 个人调用 Credential；保留并修复独立的本人身份验证 Challenge、Team/默认 Team 映射、本人软解绑及管理员只读/停用/审计界面，管理员不得代解绑
- [x] 4.5 删除旧 Capability/Connection/Handler 单元和集成测试，并为不存在的旧端点增加回归

## 5. 永久删除 Resource Mapping 与旧工具发布控制面

- [x] 5.1 删除 Application Resource Binding/Mapping、Builtin Tool Resource Mapping、解析矩阵和 runtime snapshot 代码
- [x] 5.2 删除 Built-in Tool Installation/Evidence/Release 生命周期写操作，保留只读 MCP Manifest 目录
- [x] 5.3 简化工具资源管理，保留 Draft/verify/publish/disable/archive 与 Secret 选择，删除 activation/Last Known Good/Application binding
- [x] 5.4 简化 resource-reset，仅处理工具资源与 revision，不处理 Application Mapping/runtime generation

## 6. 永久删除 Internal API Platform

- [x] 6.1 删除 `internal_api_platform`、`local_internal_api_platform`、mock entrypoint 和 InternalApiClient/service-token 代码
- [x] 6.2 将仍需的 SQL/Redis/Loki/Oracle 安全实现迁入 MCP Tool Runtime 所有模块后删除旧包
- [x] 6.3 删除 Internal API Platform Docker targets、Compose services/profiles/depends_on/networks 与健康检查
- [x] 6.4 删除 Internal API server/client Token secrets、挂载、issuer/verifier、usage 和轮换配置
- [x] 6.5 从 `.env.example`、Settings、DB runtime config 和 loader 删除 `INTERNAL_API_*`、`FEATURE_REAL_INTERNAL_TOOLS`

## 7. 数据库破坏性迁移

- [x] 7.1 新增迁移，回填可确定的 Agent/Application/Job MCP Tool identifier/schema hash；不新增业务目标冻结字段
- [x] 7.2 在迁移中拒绝仍被活动发布或在途 Job 引用且无法确定转换的旧数据
- [x] 7.3 删除 Capability、Handler、API Connection、用于业务调用的个人 API Credential、Resource Mapping、Tool Release 和 Internal API runtime generation/activation 表及旧 JSON 字段；不得删除 ONES 身份事实
- [x] 7.4 保留工具资源、平台 Secret、模型连接、渠道、角色、用户、ONES 身份/Team/验证时间、Job/Tool Call/Delivery 历史并验证迁移幂等
- [x] 7.5 更新 seed、测试数据重建、备份恢复和迁移器测试
- [x] 7.6 通过向前迁移删除遗漏的 Application Target、Job Execution Scope 表与 Job 目标列、旧 `permission_policy`/`platform_access_grant`/清理操作表和全部残留 `INTERNAL_API_*` config definition，同时保留统一 RBAC、身份、会话隔离与历史 Job 主记录
- [x] 7.7 新增静态向前迁移，为最终保留的 PostgreSQL `public` 项目自有表和全部字段补齐中文注释，排除迁移账本、系统表和第三方扩展表

## 8. 文档、规格与部署清理

- [x] 8.1 更新 README、backend README 和工具验收文档为 `Runtime -> tool-mcp -> Resource` 链路
- [x] 8.2 删除 Internal API Platform、Capability/Handler/Connection/Resource Mapping 的过期文档和 UI 文案，并明确 ONES 身份绑定不等于业务调用凭据
- [x] 8.3 清理活动 `migrate-claude-agent-sdk-to-typescript` 中被双 Runtime 主规格取代的旧 MCP 适配内容
- [x] 8.4 更新 `.env.example` 与部署脚本，明确保留 Runtime Grant、Model Probe Token 和 Master Key
- [x] 8.5 删除旧授权清理 CLI/service、DB-backed 测试权限兼容层和 seed/运行时 grants 中的旧表引用，将回归测试迁移到统一 RBAC 或显式测试替身

## 9. 验证与验收

- [ ] 9.1 运行后端格式、静态检查和聚焦/全量测试
- [x] 9.2 运行前端测试、类型检查和生产构建
- [x] 9.3 运行 Python/TypeScript Runtime lint、typecheck、合约和测试
- [x] 9.4 验证空库迁移、已有库升级、迁移失败关闭与 Compose `config --quiet`
- [x] 9.5 构建受影响镜像并验证 `tool-mcp`、两个 Runtime、Worker、API 和 Admin Web readiness
- [x] 9.6 验收 Python/TypeScript 的 test MySQL schema/query、普通问候、权限拒绝和钉钉交付链路，并验收 ONES 本人绑定/重验/默认 Team/解绑与管理员只读停用边界
- [x] 9.7 运行 OpenSpec 全量 strict validation、git diff check 和旧组件全文残留扫描
- [x] 9.8 在新备份后升级运行库，验证旧表/列/config definition 不存在，且用户、角色、成员、应用授权、ONES 身份、工具资源、Secret、会话和历史 Job 数量保持预期
- [x] 9.9 增加最终 schema 注释清单覆盖门禁，并在备份后升级运行库，验证项目表和字段的 PostgreSQL 注释覆盖率均为 100%
