# Runtime SDK 升级与部署验证（2026-11-06，Asia/Shanghai）

本次按用户授权升级 SDK、补齐源码权限失败阻断和初始化审计，测试后更新两个 Runtime；不启动模型提取。保留工作区已有状态机实现与人工审校候选，不提交 Git、不重跑旧构建、不改写冻结 Publication。

## 实现

- `pyproject.toml` 固定 `claude-agent-sdk==0.2.178`，使用随包 CLI 2.1.318。[官方 0.2.178 发布记录](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.178)
- 源码提取的全局 `PreToolUse` 设置 `on_failure="block"`；已知校验错误沿用有界诊断，未知授权异常返回固定拒绝。 malformed event 同样拒绝，不返回异常正文或更新后的参数。SDK/CLI 失败阻断能力自 0.2.177 引入。[官方 0.2.177 发布记录](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.177)
- 提取审计仅投影 SDK `system/init` 的工具名、原生 Skill 名、MCP 名称/状态及运行 SDK/CLI 版本。列表有界，缺失为 `null`，非法或超限为 `metadata_complete=false`；不复制 init 的路径、认证字段或其他正文，不启用 SDK 消息/API 正文采集。普通 Job 原审计行为不变。
- 保持宿主注入冻结 Skill、Read/Glob/Grep/Write/Edit、无 MCP/Bash 的提取方式；此次没有切换到 SDK 原生 Skill 加载。

## 验证

在已升级的本机 Python 环境运行下列 13 个测试文件，**367 passed in 82.04s**：

```text
test_code_knowledge.py
test_code_state_machines.py
test_python_runtime_run_audit.py
test_python_agent_runtime.py
test_python_runtime_internal_architecture.py
test_runtime_replica_pool.py
test_runtime_http_client.py
test_runtime_readiness.py
test_agent_runtime_protocol_contract.py
test_agent_runtime_compose_security.py
test_agent_run_audit_repository.py
test_python_file_mcp_runtime_bridge.py
test_sdk_failure_metadata.py
```

新增回归覆盖真实 SDK HookMatcher 配置、OSError/RuntimeError/TypeError 与畸形事件拒绝、flat/nested/SDK SystemMessage 三种 init 形态、额外工具可观察、字段过滤/缺失/容量边界、正文不落审计、审计分块往返及普通审计保留。通过受影响文件 Ruff check/format、三个 Runtime 源文件 mypy、pip check、git diff --check 和本 change 的 OpenSpec strict 校验。

在新 Runtime 镜像运行 `backend/tests/support/claude_sdk_init_smoke.py`：

```sh
docker run --rm -i --network none --read-only \
  --tmpfs /tmp:rw,size=256m,mode=1777 --entrypoint python \
  enterprise_agent-python-agent-runtime-a - \
  < backend/tests/support/claude_sdk_init_smoke.py
```

该容器无凭据/源码挂载，实际 SDK 与 bundled CLI 控制握手通过，接受 `on_failure=block`，SDK=0.2.178、CLI=2.1.318，`prompts_sent=0`。测试容器已由 `--rm` 删除。此检查没有发送 query，没有观测真实模型会话的 system/init 或工具执行；真实提取与 Provider 工具循环不计为已验收。

## 两个 Runtime 已更新

部署目标为本机 Compose 项目 `enterprise_agent`，使用既有 `docker-compose.yml` 与 `docker-compose.code-knowledge.yml`。复用已挂载的专用凭据文件路径，没有读取、生成或轮换凭据内容。构建时使用临时 BUILDX_CONFIG，避免写入受限的用户 buildx 状态目录；仅构建 Runtime target，再以 `--no-deps --no-build --force-recreate` 替换两个 Runtime。

更新前分别写入排空标记，并复核：无活动 Job、无 RUNNING 或已受理但未确认停止的 Invocation。没有中断正在执行的任务。

| 核验项 | runtime-a | runtime-b |
| --- | --- | --- |
| SDK / CLI | 0.2.178 / 2.1.318 | 0.2.178 / 2.1.318 |
| `/ready` / pool | true / true | true / true |
| busy / draining | false / false | false / false |
| 容器健康 | healthy | healthy |
| 用户 / 根文件系统 | 10002:10002 / 只读 | 10002:10002 / 只读 |
| 来源 / 产物卷 | 只读 / 可写 | 只读 / 可写 |
| MES 身份目录 | mes-code-identities/v3 | mes-code-identities/v3 |

两个容器使用同一镜像：

```text
sha256:6371793facb69bdf11d942fcfa1820faa106d94e8d8e2e7f4dc8f862c3c1e4c7
```

对镜像内 `backend/app/python_runtime`、`backend/app/shared` 和镜像按白名单复制的 `knowledge/domain` 共 74 个 Python 文件逐个计算 SHA-256，两端相同且均与当前工作区对应文件相同。工作区另有 20 个非 Runtime 知识模块未进入此精简镜像，不将整个工作区文件数当成镜像文件数。按相对路径和内容聚合的镜像代码摘要：

```text
fc7602da3b79a0ce994e8a05d1ff237adea3777a165df10e0b09885c68616a01
```

两端目录与当前 API 均为 v3，目录摘要一致：

```text
22ebb4c54120b11927de80f6e12cca0e7b3efea75c079f75f137ea9869c3953b
```

现有池 build identity 仍为 local-dev，未伪造新的 Git 发布标识；本次实际部署身份以镜像和逐文件摘要为准。协议保持 1.5。

## 提取保持关闭

部署前后代码来源 `enabled=0`、`demand_enabled=0`，提取 Job 总数均为 18，活动 Invocation 为 0。本次未发模型提示词、未新增提取 Job、未调用模型连接 probe、未索引或启用知识候选。原有真实 SVN/模型提取/问答验收欠账不补勾；新版运行审计在未来获准任务收到 SDK init 时产生，不回填旧任务。
