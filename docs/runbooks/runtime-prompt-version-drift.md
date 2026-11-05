# Worker / Runtime 提示词版本不一致

适用错误：请求期望 `agent-system-prompt-v8`，而 Runtime 观测为 v10，或其他版本组合。
这证明该次执行的请求和 Runtime 模板不同；仅凭错误不能判断一定是旧 Worker，因为
`agent_runtime_request_snapshot` 可能保存了升级前的冻结请求。

## 先区分三种版本

1. checkout 的 `backend/app/shared/tool_contract.py` 常量：下一次构建的代码版本。
2. 每个运行容器里的常量：实际部署的镜像版本。`restart` 不会用新代码替换旧镜像。
3. Job 的冻结请求版本：恢复时保持原值，不随当前代码更新。

2026-11-05 本机只读核对为两个 Worker、两个 Runtime 均为 v10，而 checkout 为 v11。
这是当时的本机快照，不证明生产版本，也不是建议继续固定使用 v10。

在生产实际 Compose 项目目录执行以下只读核对；如生产使用额外 Compose 参数，应沿用原参数。
命令遍历所有运行副本，不只核对 `agent-worker-1`。只输出容器名、镜像 ID、模板版本和构建标识：

```bash
for container in $(docker compose ps -q api-server agent-worker python-agent-runtime-a python-agent-runtime-b); do
  docker inspect --format '{{.Name}} image={{.Image}}' "$container"
  docker exec "$container" python -c 'from app.shared.tool_contract import PROMPT_TEMPLATE_VERSION; from app.shared.build_identity import build_identity_from_environment; identity = build_identity_from_environment("inspection"); print(PROMPT_TEMPLATE_VERSION, identity.source_revision, identity.build_id)'
done
```

还应对照 `docker compose ps -a` 检查停机/遗漏副本与生产预期拓扑。不要使用完整 `docker inspect`、
`env` 或解析后全量 Compose 配置做日志采样，因为其中可能含凭据。

如果所有运行副本版本一致，使用已有授权数据库运维入口，仅查询指定 Job 的安全字段：

```sql
SELECT i.invocation_id, i.state, i.node_id, i.instance_id,
       s.request_json::jsonb #>> '{prompt,template_version}' AS request_prompt_version
FROM agent_runtime_invocation i
JOIN agent_runtime_request_snapshot s USING (invocation_id)
WHERE i.job_id = '<JOB_ID>';
```

不要查询或导出完整 `request_json`、消息正文、运行审计正文或认证信息。

## 生产恢复

- 某个 Worker/Runtime 仍旧：按生产发布流程从同一提交构建并重建所有相关副本。至少核对
  API、全部 Agent Worker、两个 Runtime，以及执行链要求同一构建身份的 File MCP 等组件。
  仅 `restart` 或只构建 Runtime 不足以保证一致。
- `BUILD_SOURCE_REVISION`、`BUILD_ID` 必须代表本次真实发布，不能所有版本都填写 `local-dev`。
  它们是构建参数；应进入同一批镜像，不通过修改运行环境伪装成一致。
- 更新前处理在途任务，避免在模型执行中强制杀死 Runtime。RUNNING 或结果未知的调用先按
  原 invocation/digest 恢复和确认停止，不自动换新 invocation 重跑。
- 如果是已冻结的旧请求，禁止直接修改模板版本、request digest 或历史观测。已存终态按原事件
  恢复；确定失败且原执行已停止后，再按授权的新 Job 流程重试。
- 发布后重新核对所有副本，使用新的合成请求做验收。知识库分块、向量索引与这个问题无关。

## 新防线的行为

`prevent-runtime-prompt-version-drift` 增加两层前置检查，保留既有工具契约严格校验：

- `/version`、`/ready` 返回当前 `prompt_template_version`。平台被动探针返回安全的实际/期望版本及
  `prompt_status`；缺少声明、声明不合法、两接口不一致或版本不符，均不可接新执行。
- 池为 PREPARED 请求使用其冻结版本选节点；没有匹配节点时使用既有有界准入等待。
  Runtime 还会在占槽/admit 前拒绝漏过探针的旧请求，返回 `runtime_prompt_version_mismatch`。
  新 Worker 将其显示为统一更新 Agent 服务副本的提示。
- 已运行/终态恢复不要求当前模板版本相等，因为不会重新构造 Prompt。节点、构建身份、
  digest 及原事件的严格核对保持，不改写历史事实。

旧 Runtime 没有新增版本声明，因此新探针会将其标记不可接新执行，需要协调发布。普通存活
检查不能代替组件一致性检查；本修复也不会自动升级生产镜像。

## 验证边界

本地合成测试覆盖版本一致/缺失/非法/错配、按冻结版本选节点、占槽前拒绝、请求不变、
升级后的运行与终态恢复、安全错误投影。未发送真实钉钉消息、未重启本机服务，生产连接和
发布尚未验收。变更规格见[前置版本校验](../../openspec/changes/prevent-runtime-prompt-version-drift/specs/execution-delivery/spec.md)。
