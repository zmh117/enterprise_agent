# 2026-11-04 统一主 Compose 验证记录

## 已确认的运行事实

- 原 Job `job_cb55fde4739f4f28971799602ce336a8` 两次目录调用均为 `knowledge_readability_failed`，API 同时记录内部服务身份兑换拒绝。原 API 缺少知识 bootstrap 配置和挂载；Knowledge MCP 已配置。
- 仅用主 `docker-compose.yml` 完成配置校验、相关镜像构建及 `up -d --no-build`。根文件默认包含七个知识常驻服务；两个模型准备任务正常退出；一次性检查/导入工具不默认执行。
- 已停止并精确移除 `enterprise-knowledge` 的六个旧知识容器，不删除卷；该旧项目没有运行中的容器。
- 新部署复用 `enterprise_agent_knowledge-models`、`enterprise_agent_knowledge-reranker-models`、`enterprise_agent_knowledge-qdrant`、`enterprise_agent_knowledge_ops_state`。Qdrant 只有一个写实例；同步挂载其数据卷为只读。
- 迁移前后均为 3 个知识库、15,778 条文档；既有采集绑定仍 `enabled=0`、`schedule_enabled=1`，没有启用采集或改授权。
- Knowledge MCP 使用正常服务客户端向 API 兑换身份成功，只核对布尔结果和安全审计，不输出认证材料。
- 用户重新从原钉钉会话发起 Job `job_669ca29773684bfe90238b6e478bbf38`，北京时间 15:55:41 开始、15:55:52 成功结束。目录工具 `SUCCEEDED`，耗时 2689 ms，安全审计 `returned=2, has_more=false`，内部连接解析成功。
- 用户再次发起真实检索 Job `job_9a7f4e28c2cc4cc4a026c8e6f646f956`。目录查询再次成功（2575 ms）；三次检索分别在 59835、59862、59895 ms 返回 `knowledge_search_budget_exhausted`，另一次在 55175 ms 返回 `knowledge_readability_failed`。该次可读性检查的 ONES 授权阶段成功，Provider 阶段返回 `ones_provider_unavailable`。
- API 和 ONES MCP 的既有 ONES 目标均为 `http://host.docker.internal:19121`，从服务容器探测该端口不可达。该目标是本地 ONES Mock；未启动 Mock、切换真实 ONES、修改权限或调整检索超时。约 60 秒失败的具体触发层尚未确认，不能归因为同一个 ONES 故障。
- `knowledge-check ready` 返回 0，覆盖 schema、Qdrant、两套 Embedding、重排及 MCP 服务就绪。
- 实际受管构建任务 `fe49180abd9c44b6bacfd927c6aadec1` 和启动任务 `a91ee57da3ba4fbcad6b8f3263d6d25b` 均 `SUCCEEDED`。启动前后 API、PostgreSQL、执行器容器 ID 和启动时间一致，验证 `--no-deps` 操作边界。

## 本地检查

- 首轮知识部署、在线合同、同步、操作状态机、向量及恢复测试：119 passed，3 skipped。
- 最终知识部署、在线合同、同步、操作状态机、存储连接、Service Principal 和可读性桥测试：187 passed，1 skipped（需独立 PostgreSQL 并发测试环境）。
- 内容网络名称调整后的向量及同步恢复测试：71 passed，2 skipped。
- 扩大 Compose 回归：168 passed，1 skipped，4 failed。四项失败均为旧测试引用不存在的 `python-agent-runtime`，实际已为 a/b 两个服务。使用修改前 `HEAD:docker-compose.yml` 和 `.env.example` 逐项执行同样测试，均复现相同 KeyError；未修改无关 Runtime 实现或放宽测试。
- Ruff check/format、相关执行器 mypy、OpenSpec change/spec 严格校验、Markdown 本地链接检查及 `git diff --check` 通过。

## 旧测试与替代覆盖

| 原合同 | 当前覆盖与依据 |
| --- | --- |
| 知识服务必须 opt-in，叠加文件/多个 profile | `test_default_main_file_starts_all_resident_services_and_prepares_models`：按本 change 验证默认服务、一次性任务、模型依赖及内容网络 |
| 独立知识 DSN 必填 | `test_build_database_secret_and_maintenance_boundaries`、在线默认连接测试：同平台连接唯一事实源，不引入第二套连接入口 |
| 独立项目天然不包含平台服务 | 执行器命令测试和真实受管启动：固定根文件、服务名单、`--no-deps`，API/PostgreSQL/执行器身份不变 |
| 模型及内容卷可随 profile 创建 | external 卷默认名/覆盖测试和真实迁移前后卷名、内容数量核对：避免隐式空库 |
| 可选 daemon 的部署开关 | 受管默认同步服务测试；原 CLI 默认关闭、计划权限、恢复、健康及拒绝路径测试继续保留 |
| 镜像、角色 Secret、离线模型、只读文件系统、资源限制和网络隔离 | 在线镜像/Secret 测试、向量隔离测试、Service Principal 测试继续保留并改用主文件；Qdrant 默认沿用现场回环端口 |

## 验收边界

用户已明确选择“本次只完成统一部署，保留此问题”。本次统一部署、服务就绪、内部身份兑换及真实授权目录查询验收通过；实际检索未通过，保留 ONES 目标不可达和约 60 秒检索预算失败两项后续问题，不以 Job 结束成功代替工具调用成功。

后台调试入口检查到原用户无调试执行权限，未为验收改权限或创建绕过授权的 Job；工具验收均来自用户在原钉钉会话主动发起的请求。真实采集未执行，采集计划保持原关闭状态。该部署验收不证明 ONES 连通性、检索质量或采集成功。
