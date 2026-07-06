# Agent 平台配置 API 设计说明

## 目标

`agent-platform-config-api` 把原来散落在 YAML/env 和扁平配置表里的平台配置逐步落到 PostgreSQL，为后续 Web 配置平台打基础。第一版仍保持只读诊断 Agent 边界，只配置诊断链路需要的环境、基地、车间、只读资源、权限和诊断流程模板。

## 是否需要和聊天记录分库存放

第一版不建议物理分库。Web 配置、Agent job、聊天记录、工具调用和审计先放在同一个 PostgreSQL database 中，通过领域模块和表前缀隔离：

- `platform_*`: 平台配置域。
- `agent_workflow_*`: 拖拽编排模板域。
- `agent_*`: Agent 运行时任务、消息、步骤、工具调用和产物。
- `delivery_*`: 结果投递链路。

这样本地部署、迁移、测试和审计关联都更简单。聊天、工具调用、审计属于高增长运行数据，后续如果数据量明显增长，优先做按时间分区、归档和冷热数据拆分，再决定是否把运行数据迁到独立库。配置域通过 repository 边界访问，未来拆库不需要改 Web API 的领域语义。

## DDD 模块边界

### `platform_config`

负责平台配置生命周期，不负责执行 Agent job。

- `domain`: Environment、Base、Workshop、ResourceBinding、SecretReference、AccessGrant、ConfigAudit。
- `application`: 配置校验、权限检查、YAML import/upsert、topology snapshot、配置审计。
- `infrastructure`: PostgreSQL repository、secret reference 解析边界。
- `api`: `/api/platform/*`。

### `workflow`

负责 Web 拖拽编排模板，不负责运行复杂 DAG。

- `domain`: AgentWorkflowTemplate、WorkflowNode、WorkflowEdge、WorkflowPublication。
- `application`: 图校验、节点安全边界、发布快照。
- `infrastructure`: PostgreSQL repository。
- `api`: `/api/agent/workflows/*`。

### `internal_api_platform`

只消费配置快照，不拥有配置生命周期。启动时优先从 PostgreSQL 构造 topology。只有 DB 没有启用 topology 时，才使用 `INTERNAL_PLATFORM_TOPOLOGY_FILE` 指向的 YAML 做本地 fallback。DB 配置存在但有错误时会暴露 `database-invalid`，不会静默回退。

## 核心表

平台配置表：

- `platform_environment`: 环境，例如 `sanjiu`、`mmk`。
- `platform_base`: 基地，归属环境，保存默认数据库引擎。
- `platform_workshop`: 车间，保存表前缀、Redis key 前缀和 Loki label。
- `platform_secret_reference`: 密钥引用，只保存 `env:NAME`、`secret://...`、`vault:...`、`kms:...`，不保存真实密钥值。
- `platform_resource_binding`: DB、Redis、Loki、ER context、business-flow context 资源绑定。
- `platform_access_grant`: 用户、组、角色或服务账号的 topology/tool 授权。
- `platform_config_audit`: 配置变更审计。

工作流表：

- `agent_workflow_template`: 可编辑流程模板。
- `agent_workflow_node`: 拖拽节点和节点配置。
- `agent_workflow_edge`: 节点连线、端口和条件。
- `agent_workflow_publication`: 不可变发布快照，后续运行时应读取这里而不是草稿。

## 密钥策略

PostgreSQL 只保存密钥引用，不保存真实密钥值。

允许示例：

```json
{
  "secret_refs": {
    "password": "env:ORDER_DB_PASSWORD"
  }
}
```

禁止示例：

```json
{
  "config": {
    "password": "plain-secret"
  }
}
```

API、snapshot、审计摘要都只返回引用，不返回解析后的真实值。Internal API Platform 只有在 infrastructure 层真正连接 DB/Redis/Loki 时才解析引用。

## 主要 API

平台配置：

- `GET /api/platform/environments`
- `POST /api/platform/environments`
- `POST /api/platform/environments/{code}/enable`
- `POST /api/platform/environments/{code}/disable`
- `GET /api/platform/bases`
- `POST /api/platform/bases`
- `GET /api/platform/workshops`
- `POST /api/platform/workshops`
- `GET /api/platform/resource-bindings`
- `POST /api/platform/resource-bindings`
- `GET /api/platform/secret-references`
- `POST /api/platform/secret-references`
- `GET /api/platform/access-grants`
- `POST /api/platform/access-grants`
- `POST /api/platform/import/topology-yaml`
- `GET /api/platform/topology-snapshot`

工作流配置：

- `GET /api/agent/workflows`
- `POST /api/agent/workflows`
- `GET /api/agent/workflows/{code}/nodes`
- `POST /api/agent/workflows/{code}/nodes`
- `GET /api/agent/workflows/{code}/edges`
- `POST /api/agent/workflows/{code}/edges`
- `POST /api/agent/workflows/{code}/publish`
- `GET /api/agent/workflows/{code}/publications/latest`

写配置接口需要 `x-admin-user-id`，并要求该用户在 `permission_policy` 中有：

```text
resource_type = platform_config
resource_code = *
effect = allow
```

本地 seed 已给 `local-user` 增加该权限。

## 本地验证示例

导入当前 YAML：

```bash
curl -s -X POST http://127.0.0.1:8000/api/platform/import/topology-yaml \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"path":"config/internal_platform_topology.example.yaml"}'
```

查看 DB-backed snapshot：

```bash
curl -s http://127.0.0.1:8000/api/platform/topology-snapshot
```

创建工作流模板：

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/workflows \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"code":"order-diagnosis","name":"订单诊断","project_code":"default"}'
```

## 后续扩展

- Web 前端可以直接基于 `agent_workflow_node.position_json`、`ui_json` 和 `agent_workflow_edge` 做拖拽画布。
- 运行时接入流程模板时，只读取 `agent_workflow_publication.graph_snapshot_json`。
- 高增长运行数据先做分区和归档，再评估是否拆独立 runtime/audit database。
- 密钥管理后续可接 Vault/KMS，但 PostgreSQL 仍只保存引用。
