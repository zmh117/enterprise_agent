# 11.2 Compose 叶子深度与 placement 验收证据

执行日期：2026-08-06（Asia/Shanghai）

## 隔离方式

- 新增显式 profile `builtin-tool-acceptance` 下的一次性服务 `builtin-tool-compose-acceptance`。
- 服务使用当前 `backend/Dockerfile` 的专用 acceptance target，仅在该镜像中增加测试权限适配器；默认 `api-server` target 保持不变。
- 验收运行在容器内的 SQLite 内存数据库，不依赖或修改当前 Compose PostgreSQL、RabbitMQ 和运行服务。
- 执行完整生产服务链：Topology 创建、Tool reconcile/verify/release publish、精确 Agent Publication、Resource Revision、可选 Workshop Policy、Application Draft/Publish 和不可变 Resolution Set 校验。

## 场景矩阵

| 场景 | 业务叶子 | placement | 解析数量 |
|---|---|---|---:|
| `environment-no-placement` | Environment | 缺省 | 1 |
| `base-cloud-only` | Base | cloud | 1 |
| `workshop-edge-only` | Workshop | edge | 1 |
| `workshop-cloud-edge` | Workshop | cloud + edge | 2 |

Workshop 场景均冻结同一逻辑 Workshop 的 Published 数据库前缀 Policy Revision；cloud + edge 不创建伪 Base/Workshop。

## 执行命令与结果

```text
docker compose --profile builtin-tool-acceptance run --rm --build builtin-tool-compose-acceptance
```

结果：镜像构建成功，四个场景全部输出 `ok`，最终输出：

```text
compose-acceptance builtin-tool-composition: passed scenarios=4
```

自动回归：`backend/tests/test_builtin_tool_compose_acceptance.py` 同时锁定场景矩阵并执行 runner。
