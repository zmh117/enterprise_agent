# Runtime 多副本池

本期部署边界是同一主机 Docker Compose。默认两个固定 Runtime 节点、两个 `agent-worker` 副本；每个 Runtime 进程的 Job 和模型 probe 共用一个执行槽。同一完整 Session 内串行，不同 Session 可并行。分层验收状态及单模型有界测量见 [当前验收记录](../../openspec/changes/archive/2026-10-25-add-runtime-replica-pool/evidence/acceptance.md)。

## 配置和归属

| 项目 | 约定 |
| --- | --- |
| 节点 | `python-agent-runtime-a`、`python-agent-runtime-b`；`PYTHON_AGENT_RUNTIME_NODE_ID` 分别为 `a`、`b` |
| 成员映射 | `PYTHON_AGENT_RUNTIME_NODES=a=http://python-agent-runtime-a:8091,b=http://python-agent-runtime-b:8091` |
| URL 边界 | `PYTHON_AGENT_RUNTIME_ALLOWED_HOSTS` 同时列出两节点；拒绝重定向及响应提供的任意地址 |
| 实例身份 | Runtime 每次启动生成新 UUID；所有执行、恢复、取消请求绑定预期 node/instance |
| 进程与容器 | 固定 `container_name`，禁止 `--scale` Runtime 服务；镜像显式使用一个 Uvicorn worker |
| Worker | `agent-worker` 默认两个副本，各自一个 Job、RabbitMQ prefetch=1 |
| 租约 | Worker 和 Invocation 独立；每 5 秒续租，30 秒过期；过期不可续活 |
| 等待预算 | attempt 进入可排队状态后 3600 秒；业务重试从 `next_retry_at` 开始，不因容量/恢复延期延长 |
| 执行预算 | 准入事务时刻加冻结的 `timeout_seconds`，最大 3600 秒；恢复不延长 |
| 停止兜底 | 取消或失租后 10 秒仍未退出 SDK，Runtime 前台进程退出，容器停止其子进程 |
| Broker/排空 | ACK 超时 4200000ms，正常停止宽限 70 分钟；心跳 I/O 独立于模型执行 |

修改节点数量时同时修改固定 Compose 服务、节点映射和白名单。不要在一个服务地址后放多个 Runtime，不能以 DNS 轮询或负载均衡替代归属路由。每个节点使用自己的 tmpfs、沙盒和实例 UUID。API、Worker、Runtime 使用同一 release/build identity；成员和构建身份不符时拒绝选路。

Worker 控制租约允许接管；已经 RUNNING 的 Invocation 执行归属不转移。网络错误先查询持久化状态：PREPARED 可再次准入，RUNNING 只恢复原实例，TERMINAL 只重放或报告中断。禁止删除归属记录、改回 PREPARED、增加 retry_count 来“修复”失联任务。

## 升级门禁

这是协调切换，不能滚动混跑旧 Worker。不要把旧 RUNNING 行自动解释为新协议的归属。

1. 暂停渠道、Webhook、调试等新任务入口，等待现有执行结束。记录受影响 Compose 项目及服务清单，保留数据库备份。
2. 排空 Job/重试队列，停止旧 `agent-worker`、调度器及旧 Runtime 容器；确认没有对应旧进程或外置消费者。明确处理旧非终态任务，不能直接放入新池重跑。
3. 用新镜像执行只读门禁（支持 schema 146 或当前 head）：

   ```sh
   docker compose run --rm --no-deps agent-worker python -m app.cli.runtime_pool_preflight
   ```

   退出码 0 只证明数据库无非终态 Job、执行/重试队列无待处理消息和消费者。退出码 1 表示事实不可读取，2 表示仍有阻塞；均不可继续切换。容器和旧进程已经停止仍需操作人员核实。死信只做人工追溯，不在本次切换自动重放。

4. 执行现有 migrator 到 147，并运行既有 `app.cli.apply_agent_runtime_grants` 流程更新角色。Runtime 只能读取所需绑定并写执行元数据/事件/终态；没有 Job、Session、Delivery、RBAC 写权限，也不能写请求快照。
5. 同批更新 API、Worker、Runtime 和相关读取组件。启动两个固定节点、两个 Worker 与调度器；核对 `/version` 的 node、instance、pool_enabled、build identity，以及 `/ready` 和池状态。旧服务名 `python-agent-runtime` 不再是 Compose 运行服务名，镜像 build target 保持不变。
6. 用合成任务验证不同会话并行、同会话顺序和取消，再开放入口。真实 Provider 验收前不要把确定性测试通过当作模型运行验收。

## 排空与替换节点

先写节点自己的排空标记：

```sh
docker compose exec python-agent-runtime-a touch /tmp/python-agent-runtime/draining
```

节点停止接受新 Job/probe，现有执行、重连、取消和终态读取继续工作。通过 Job 详情或只读 SQL 核对该 node 没有 RUNNING 或未确认停止的执行，再停止/替换容器。`docker compose stop` 默认等待正常排空，可能持续到最长任务完成；需要紧急强制结束时明确记录受影响 Invocation，其结果可能变为 unknown，不能自动重跑。

同一固定容器重启后 UUID 改变，调度扫描验证受控地址、构建身份和 node 后，可为旧实例的已中断 Invocation 记录停止证据。这一证明只适用于固定节点单容器/单进程约束。地址指向了另一个主机、复制容器或旧进程仍活着时，应隔离节点并停止所有旧实例，再人工处理；不能伪造 `execution_quiesced_at`。

重新开放同一运行实例可删除排空标记；容器替换时 tmpfs 自然清空。仅删除明确的 `draining` 文件，不删除沙盒或归属数据。

## 取消、重连和异常处理

- 用户通过 `POST /api/agent/jobs/{job_id}/cancel` 取消；接口要求 `jobs.manage`、目标 Job 访问权限与 CSRF。服务端先持久化取消，再由原 owner 通知/轮询收敛。客户端断连、Worker 正常退出不会隐式取消。
- `cancel_requested` 表示执行尚未确认停止；`cancelled` 表示未启动任务已取消；`already_terminal` 表示终态先提交；`outcome_unknown` 表示已有中断终态。Job 保持既有状态枚举：取消为 FAILED + `runtime_cancelled`。
- Worker 失联后等待控制租约过期，调度器复用同一 invocation/digest 接管。不要手动重置 Job；保留 Outbox 恢复事实。
- Runtime 失联收敛为 FAILED + `runtime_invocation_outcome_unknown`。若停止证据为空，该 Session 后续任务仍被阻塞；其他 Session 可继续。恢复原节点或确认固定容器已替换后，由扫描记录停止证据。
- 全池不可用时，已接受的 Job 通过 Outbox 有界延期（默认 1–5 秒抖动），不增加业务 retry_count；新请求按现有就绪门禁拒绝。准入预算耗尽为 TIMEOUT + `runtime_admission_timeout`，即使 Broker 没有送达 Worker 也由调度扫描收敛。
- 数据库不可用时不能确认归属、续租、结果或延期；不得 ACK 成功或新建业务 attempt。Runtime watchdog 独立于数据库 I/O，超时执行会被停止或容器退出。恢复数据库后观察同一 Invocation 收敛。
- 只有明确可重试的业务失败且 Invocation 已停止，才允许新 attempt。后续会话任务不能越过这个重试。

## 状态与保留

现有 Job 详情增加 `runtime_execution`：Invocation、摘要、node/instance、执行/准入/取消/停止时间、等待原因和下一次观察时刻；同时显示 Worker 领取版本与租约。调度 metrics 增加状态计数、等待原因计数、未停止执行数和最早取消时间。池状态区分 READY、DEGRADED、UNAVAILABLE；busy 是容量占用，不是依赖故障。

请求快照、事件、终态正文仅在 Job 已终结且 Invocation 已终结并确认停止后才可清理；`RuntimePoolStore.prune_body` 验证这些条件。生命周期身份随 Job 保留，普通读取不触发清理。当前没有按 TTL 自动删除运行结果的定时任务；现有 ledger TTL 参数不会越过这些条件。正文清理后恢复返回 `runtime_recovery_expired`，不能重新执行。普通状态、队列和运维报告不得输出快照正文、凭据或认证 Header。

## 模型失败与跨节点重试排查

`claude_inconsistent_result` 表示 SDK/CLI 的失败结果同时带有成功 subtype 等标记，不能据此确定上游根因。SDK 的 API 失败也可能返回 `subtype=success`、`is_error=true`；HTTP 状态、`terminal_reason` 才是进一步定位的证据。不要把这类结果当成成功，也不要仅靠增加重试次数掩盖持续故障。

明确模型认证失败会优先返回 `runtime_model_authentication`（HTTP 401 或 SDK 认证标记），并提示管理员检查更新模型连接的 API Key；403/权限错误返回 `runtime_model_permission_denied`。这两类错误均使用 `CONFIGURATION`，不创建后续自动重试，任务详情和钉钉等原回复渠道使用同一安全原因。模型连接测试使用相同分类。401 本身不能区分填错、过期或撤销；没有上游认证证据时仍保留不一致结果分类。旧 SDK 仅支持从已确认失败的 `API Error: 401/403` 信封提取状态，不扫描普通消息或 stderr 猜测认证失败。

新的失败记录在完整运行审计的 `error.sdk_result` 保存不含正文的结构化字段：`subtype`、`is_error`、`api_error_status`、`terminal_reason`、`error_count`、`result_present`、`duration_ms` 和 `num_turns`（上游未提供的数值字段不补猜）。Worker 将其投影到 `job.retry.scheduled` 和 `job.dead.persisted` 的 `sdk_result`，放在可能截断的其他诊断明细之前。未知 subtype/reason 只显示 `unknown`，不把响应正文、errors 文本或 stderr 复制进该摘要。旧记录不会自动补齐。

同一个 Job 可以在首次失败并确认执行停止后，使用新的 attempt 在另一节点重试。收到 HTTP 请求或重放已有终态不等于再次运行模型。排查两个 Runtime 是否重复执行时，在部署数据库中只查询以下元数据（替换 Job ID）：

```sql
SELECT invocation_id, attempt, node_id, state, accepted_at,
       execution_quiesced_at, terminal_at, terminal_code
FROM agent_runtime_invocation
WHERE job_id = '<job_id>'
ORDER BY attempt;

SELECT id, status, retry_count, max_retry_count, next_retry_at, last_error_code
FROM agent_job
WHERE id = '<job_id>';
```

不同 attempt 的执行必须满足：前一次 `execution_quiesced_at` 不晚于下一次 `accepted_at`。同一 invocation 只有一个数据库 owner；若节点日志显示它在两个节点真正启动了 SDK，需要继续核对节点是否共享数据库、节点/实例标识和部署版本。仅看到两个节点均收到请求，不能认定重复执行。对外只提供上述元数据及安全诊断字段，不导出完整运行审计或原始消息。

## 隔离验收与回退

三节点拓扑和可阻塞确定性 Provider 位于 [验收脚本](../../backend/tests/support/runtime_pool/run.py) 与 [Compose](../../backend/tests/support/runtime_pool/compose.yml)。它们使用独立项目、临时 PostgreSQL/RabbitMQ、生成的测试密钥，不能连接部署数据库。按脚本 `init` 输出目录依次执行 `start`、所需 case、`cleanup`；镜像需先构建为 `ea-runtime-pool-test:local` 和 `ea-runtime-pool-worker-test:local`。故障注入只安装在测试挂载模块，不进入产品镜像。

发布失败时先暂停入口、排空或明确终止新执行，停止所有新 Worker/Runtime，再决定前滚修复或整体恢复备份与旧镜像。不要让旧镜像继续写新协议的未终态 Job，不做在线混合回退。没有停止证明的执行必须先处理，不能以数据回滚掩盖仍在运行的模型进程。

## 真实模型的有界复验

只有明确授权真实模型调用时，才使用 [真实验收入口](../../backend/tests/support/runtime_pool/real.py)。普通 `run.py` 确定性场景不会自动读取现有受管模型。

1. 确认本地现有 PostgreSQL 容器及数据卷，记录原启动状态；只有在需要时启动 `postgres`，不要运行源数据库 migrator。入口按现有 `default-deepseek-anthropic` ready revision 读取受管配置，所有源查询使用只读事务；不会创建或轮换真实凭据。
2. 执行 `real.py init --master-file <现有 Master Key 文件绝对路径>`，记录输出的独立临时目录。仅将所选加密记录经内存复制到测试数据库，真实 Master Key 保持只读挂载。源码根目录运行 Python 时设置 `PYTHONPATH=backend:.`。
3. 在独立终端运行 [资源采样器](../../backend/tests/support/runtime_pool/sample_resources.py) `<临时目录>`，其仅采样该独立 Compose 项目，最多运行 20 分钟。依次执行 `real.py warmup`、`parallel`、`serial`、`burst`、`cancel`、`takeover`，每项带 `--root <临时目录>`；任何阶段失败应先检查安全证据，不盲目重跑。总 Job 上限 18、自动业务重试 0、最多 4 轮，实际 deadline 还受 Application 策略限制。
4. 在临时目录创建 `stop-sampler` 文件并等待采样结束；执行 [收集器](../../backend/tests/support/runtime_pool/collect_real.py) `<临时目录>`。报告须保留失败尝试、源码/镜像身份、采样规模和未观测边界，不输出 Prompt、响应正文或凭据。
5. 保存安全报告后执行 `run.py cleanup --root <临时目录>`，移除该测试项目、临时数据库及生成的测试密钥。若源 PostgreSQL 原来停止且由本次启动，恢复其原状态；不得删除原数据卷或原 Master Key 文件。

当前实测见 [真实验收报告](../../openspec/changes/archive/2026-10-25-add-runtime-replica-pool/evidence/real-acceptance.md)。它覆盖现有一个受管模型与凭据版本，未验证真实多凭据切换、长任务/多轮工具负载或生产站点容量；默认两个 Runtime 的配置不因小样本吞吐自动改变。
