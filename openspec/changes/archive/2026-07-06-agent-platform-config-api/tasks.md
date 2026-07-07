## 1. 数据库与迁移

- [x] 1.1 新增 `platform_*` 表迁移，覆盖 environment、base、workshop、secret reference、resource binding、access grant、config audit。
- [x] 1.2 新增 `agent_workflow_*` 表迁移，覆盖 template、node、edge、publication。
- [x] 1.3 为配置编码、父子关系、scope、状态和 revision 添加必要索引与唯一约束。
- [x] 1.4 增加 seed 或 import 样例，确保不写入任何真实密钥值。
- [x] 1.5 增加迁移测试，验证新表可创建、约束生效、现有运行表不受影响。

## 2. Platform Config DDD 模块

- [x] 2.1 创建 `backend/app/modules/platform_config/` 的 domain、application、infrastructure、api 目录。
- [x] 2.2 实现 Environment、Base、Workshop、SecretReference、ResourceBinding、AccessGrant、ConfigAudit 领域模型和值对象。
- [x] 2.3 实现 platform config repository 接口和 PostgreSQL 实现。
- [x] 2.4 实现配置校验服务，覆盖编码唯一、父子关系、resource kind、scope、JSON schema 和 secret 泄露检查。
- [x] 2.5 实现配置审计服务，记录 create、update、enable、disable、import、publish 动作。
- [x] 2.6 实现 topology snapshot builder，从 DB 生成 Internal API Platform 可消费的运行快照。

## 3. YAML Import 与运行时配置来源

- [x] 3.1 实现当前 topology YAML 到 platform config 表的 import/upsert 服务。
- [x] 3.2 import/upsert 返回 created、updated、skipped 和 validation errors 统计。
- [x] 3.3 Internal API Platform 增加 DB-backed topology loader。
- [x] 3.4 保留 local YAML fallback，且仅在 DB 没有启用 topology 时使用。
- [x] 3.5 增加配置来源 debug/health 输出，展示 source、revision/hash、资源数量和错误摘要。

## 4. Platform Config API

- [x] 4.1 新增 `/api/platform/environments` 查询、新增、修改、启停接口。
- [x] 4.2 新增 `/api/platform/bases` 和 `/api/platform/workshops` 查询、新增、修改、启停接口。
- [x] 4.3 新增 `/api/platform/resource-bindings` 查询、新增、修改、启停接口。
- [x] 4.4 新增 `/api/platform/secret-references` 查询和维护接口，响应不得泄露真实密钥值。
- [x] 4.5 新增 `/api/platform/access-grants` 查询、新增、修改、启停接口。
- [x] 4.6 新增 `/api/platform/import/topology-yaml` import/upsert 接口。
- [x] 4.7 新增 `/api/platform/topology-snapshot` 只读快照接口。
- [x] 4.8 将平台配置 API 接入权限校验和配置审计。

## 5. Workflow 配置模块

- [x] 5.1 创建 `backend/app/modules/workflow/` 的 domain、application、infrastructure、api 目录。
- [x] 5.2 实现 AgentWorkflowTemplate、WorkflowNode、WorkflowEdge、WorkflowPublication 领域模型。
- [x] 5.3 实现 workflow repository 和 PostgreSQL 实现。
- [x] 5.4 实现图校验服务，覆盖入口节点、节点 key、边 key、边引用、只读节点类型和发布前校验。
- [x] 5.5 实现 workflow publication 服务，生成不可变 graph snapshot 和 config hash。
- [x] 5.6 新增 `/api/agent/workflows/*` 模板、节点、边和发布接口。

## 6. 权限、审计与只读安全

- [x] 6.1 平台配置变更接入操作者权限检查。
- [x] 6.2 平台 access grants 可生成运行时工具授权策略。
- [x] 6.3 DB-backed resource binding 继续执行 DB/Redis/Loki/context 工具只读 guardrails。
- [x] 6.4 审计摘要、API 响应、debug 输出和 Agent prompt 增加 secret 脱敏测试。

## 7. 测试与文档

- [x] 7.1 增加 platform config repository、YAML import、snapshot builder 单元测试。
- [x] 7.2 增加 platform config API 集成测试。
- [x] 7.3 增加 workflow graph 保存、校验、发布快照测试。
- [x] 7.4 增加 Internal API Platform 从 DB snapshot 读取资源绑定的集成测试。
- [x] 7.5 新增中文文档，说明表设计、DDD 边界、同库/分库策略、YAML 迁移和拖拽编排模型。
- [x] 7.6 运行 `openspec validate agent-platform-config-api --strict`，修复所有规格问题。
