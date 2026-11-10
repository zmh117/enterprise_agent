# 本机验证记录

验证时间：2026-11-10 20:07 +08:00。以下均为本机代码、隔离合成输入或被动部署检查，不代表真实模型业务分析验收。

## 回归

- 357 个测试、4 个子测试通过：轮次预算、Python Runtime、源码权限、执行策略、不可重试终态、HTTP Runtime、双节点池、文件 MCP 桥接和知识工具契约。
- Ruff 通过；三个变更 Runtime 模块的 Mypy 通过；`git diff --check` 通过。
- 该 change 和 `execution-delivery` canonical spec 均通过 OpenSpec strict 校验。
- 同响应多块、混合工具、重复消息、旧响应重放、缺失模型身份、并发 hook 关联、读取失败和工具总预算均有覆盖。

## 真实 SDK 与合成 Provider

脚本：`backend/tests/support/claude_turn_budget_smoke.py`。在新 Runtime 镜像中以非 root、只读文件系统、独立临时目录和 `--network none` 运行；Provider 仅监听容器内回环地址，无真实凭据或源码挂载。

SDK 0.2.178、CLI 2.1.318：

| 场景 | 观测轮次 | 计入轮次 | 免计轮次 | 结果 |
| --- | --- | --- | --- | --- |
| Glob、Grep、Read 后回答，任务上限 1 | 4 | 1 | 3 | 成功 |
| Write、Read 后再次 Write，任务上限 1 | 3 | 2 | 1 | 超额 Write 未执行，终态不可重试 |
| 三次文件工具请求，工具上限 2 | 3 | 0 | 3 | 第三次请求被工具总预算阻断 |

宿主提前结束模型流时，通过显式管理 `ClaudeSDKClient` 执行中断和关闭。测试验证 SDK 会话关闭后才返回预算失败，避免旧循环在后台继续执行。

## 容器更新

- 更新前活动 Job 和未静止调用均为 0；两个 Runtime 进入 draining 后确认不忙，停止两个 worker，再替换 Runtime 并恢复 worker。
- Runtime a 镜像：`sha256:b2ac138b8940a7b2adb79ec912630d7c6398fd8f86e7de61eb02dd6d2a732b34`。
- Runtime b 镜像：`sha256:61d0224c5cfa85f7eb8121815d01892627cc8daa5d7b2c5e328b275e10d90755`。
- 两个容器 healthy；控制面探测池状态 READY、身份 verified、提示词 MATCH、draining=false、busy=false。
- 两个节点的 `turn_budget.py`、`claude_client.py`、`mcp_config.py`、`error_mapper.py`、`executor.py`、`code_tool_errors.py` 六份代码 SHA-256 均与工作区一致。
- 两个运行中节点均通过不调用模型的预算计数冒烟检查。
- 更新后活动 Job 和未静止调用仍为 0。历史任务 `job_7436020af66448518de506a7dbde20b2` 保持 SUCCEEDED、retry_count=1，未重跑或修改历史记录。
- 未启动真实模型、源码分析或外部业务操作；未修改其他服务的配置，未提交 Git。
