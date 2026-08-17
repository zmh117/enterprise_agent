## Context

当前实现已经把内置只读工具收敛到固定的 `tool-mcp` 服务：Python Runtime 只获得部署固定的 MCP 地址，`tool-mcp` 根据 Job 固化的 Tool identifier/schema hash 和当前授权事实，在每次调用中解析唯一 Published Resource Revision，并在基础设施适配器内解析 Secret。独立 Internal API Platform、HTTP client、YAML runtime topology、Application Resource Mapping、activation generation 和专用 Token 均已退役。

当前规范仍混合两代架构，Dockerfile 也仍复制已删除的 `backend/config`。由于 `.dockerignore` 在重新包含 `backend/app/**` 后没有再次排除 Python bytecode，本地旧模块的 `__pycache__` 还可能进入构建上下文。

## Goals / Non-Goals

**Goals:**

- 让当前构建不依赖已删除目录，也不携带本地 bytecode。
- 让 canonical specs 只正向描述 `python-agent-runtime -> tool-mcp -> Published Resource Revision`。
- 明确资源在 Tool Call 时按目标、类型和可选 placement 唯一解析，Job 不固化 Application Resource Mapping 或 Resource Revision。
- 保留 RBAC、数据范围、只读策略、Secret 隔离、审计、Job provenance 和 Oracle thick 运行边界。
- 让连接事实和数据范围随同一个 Resource Draft 验证、随同一个不可变 Resource Revision 发布，避免可变 Workshop 字段在发布后静默改变运行边界。
- 为 DB、Redis 和 Loki 提供同一资源管理页面；连接与范围在界面中分区，但不创建独立 Policy 页面或 Policy Revision。

**Non-Goals:**

- 不恢复旧平台、通用 HTTP/API Capability executor、动态 MCP URL 或旧 Token。
- 不修改 archive，也不重写已应用 migration 内容或 checksum。
- 不改变 ONES 身份、ONES MCP、File Service、Agent Runtime 协议或 Tool 公开 schema。
- 不删除本地 Oracle Instant Client vendor 包。
- 不恢复已删除的 Workshop Partition Policy、Loki Scope Policy、Application Mapping 或其它独立策略生命周期。

## Decisions

### 1. 当前执行事实源固定为代码 Manifest 和标准 MCP

规范中的执行者统一为 `tool-mcp`。Runtime 只提交固定 Tool identifier/schema hash 与 Job 上下文，不直接连接 DB、Redis 或 Loki，也不调用旧 HTTP endpoint。

替代方案是只把旧服务名机械替换为 `tool-mcp`，但这会保留 fake client、HTTP path、Handler Version 和 activation 等不存在的语义，因此不采用。

### 2. 资源按调用实时唯一解析，不恢复应用映射或 LKG

每次 Tool Call 使用当前角色数据范围、Agent 提供的业务目标、资源类型和可选 placement，从 PostgreSQL 中解析一个启用 Resource Identity 的最新 Published Revision。零命中、多命中、Revision/Secret/驱动不可用均只让本次调用失败关闭，不回退 YAML、旧 revision、第一候选或 Application Last Known Good。

这与当前 `DirectResourceResolver` 一致，也避免恢复已经删除的 Application Resource Mapping 和 Job Resource Snapshot。

### 3. 历史与负向守卫保留，但不作为正向架构

Archive 和不可变 migration 中的旧名称属于历史证据；canonical spec 可保留“旧组件不得回归”的负向 requirement。任何宣称旧平台存在、启动、提供 endpoint、health 或执行工具的正向描述均删除或改写。

### 4. Docker 构建只复制现存源文件

删除 `COPY backend/config`。在 `.dockerignore` 的重新包含规则之后排除 `**/__pycache__/`、`**/*.py[cod]`，使本地已忽略缓存不进入镜像。Oracle vendor 目录继续供 `tool-mcp` 构建阶段使用。

### 5. 不改写 baseline migration

`100_baseline_v1.sql` 已进入 checksum 账本，不能为了修改历史注释而原地编辑。本 change 只处理运行代码、当前文档和 canonical specs；若最终 schema comment 仍需调整，应通过新的单调 migration 独立变更。

### 6. 连接与数据范围由同一个 Resource Revision 原子发布

`platform_resource_draft` 与 `platform_resource_revision` 增加 `scope_bindings_json`。该字段与 Provider `config_json`、`secret_refs_json` 一起参与 content hash、技术验证和发布；Published Revision 仍不可原地修改。

统一结构为 `scope_bindings[]`，每项显式声明平台目标 `environment_code`、可选 `base_code` 和可选 `workshop_code`，并按资源类型携带一种限制：

- Database：一个精确、区分方言大小写语义的 `table_prefix`；Workshop 目标必须有精确绑定。
- Redis：一个或多个不含通配/正则的完整 `namespace_prefixes`；Workshop 目标必须有精确绑定。
- Loki：Environment 或 Environment/Base 目标及一个或多个唯一 label key 的精确非空 `selector_conditions`。label key/value 来自有界发现并由管理员显式选择，不要求与 Environment/Base/Workshop 同名。

Database/Redis 在没有 Workshop 的目标上可使用显式无分区绑定；不能从相邻 Workshop、最近父级或旧 topology 字段继承。Loki 对包含 Workshop 的调用仍只选择精确 Base binding 或 Environment binding，永不自动合成 Workshop/placement label。

### 7. 逻辑统一、界面分区、一次验证发布

工具资源详情继续是唯一管理入口。连接配置与“数据范围”作为同一 Draft 的两个编辑区；保存任一部分都会增加同一个 draft revision 并使旧验证失效。技术验证覆盖连接和全部 scope bindings，发布时生成一个 Resource Revision。

Loki Draft 先通过受认证管理端 endpoint 测试连接并发现 label keys；管理员选择任意 key 后，服务端根据此前已选精确条件有界发现 values。前端只生成只读预览 selector，禁止任意 LogQL、OR、否定、正则、通配和重复 key。

## Risks / Trade-offs

- [Risk] 大量旧 requirement 与当前 requirement 交错，漏改会继续产生双重事实源 → 增加 canonical marker 扫描并执行 OpenSpec strict validation。
- [Risk] 过度删除会损失只读、授权或 Secret 约束 → 保留行为约束，只替换执行者、资源解析和部署语义。
- [Risk] Docker 构建依赖本地 Oracle vendor 包且耗时较长 → 先运行静态/单测与 Compose config，再定向构建继承 `api-server` 的关键镜像。
- [Risk] baseline SQL 仍可检索到旧示例 → 明确其为不可变迁移证据，不以修改 checksum 的方式追求文本零命中。
- [Risk] 新运行时遇到没有范围绑定的旧 Published Revision → 对 Workshop DB/Redis 和全部 Loki 调用失败关闭；管理员从旧 Revision 创建 Draft、补齐范围、重新验证发布，不改写历史版本。
- [Risk] 全局 Loki 可能包含较多目标映射 → 对 binding 数量、label 条件数、key/value 长度和发现响应统一设上限，并在发布前拒绝重复目标。

## Migration Plan

1. 生成并严格校验 delta specs。
2. 修复 Dockerfile、`.dockerignore` 和 Oracle 当前说明。
3. 通过新单调 migration 增加同 Revision 的 scope bindings，并同步管理 API、运行时和前端。
4. 同步 delta 到相关 canonical specs。
5. 运行资源范围、退役契约、MCP/Oracle 定向测试、前端测试、Markdown/OpenSpec 校验和 Compose config。
6. 定向构建 `api-server`、`file-service` 与 `tool-mcp`，确认不再引用 `backend/config`。

回滚仅需恢复本 change 修改的源文件和规格；不涉及数据库回滚、数据删除或 Secret 变更。

## Open Questions

无。用户已确认：不创建独立数据范围页面或独立 Policy Revision；DB、Redis、Loki 的连接与范围在同一个 Resource Draft/Revision 中统一验证发布；Loki label 通过连接后发现和逐级精确选择建立显式平台目标映射。
