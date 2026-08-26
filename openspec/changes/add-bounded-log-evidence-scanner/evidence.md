## 验证环境

- 日期：2026-08-26，Asia/Shanghai
- 代码目录：`/Users/mhz/Develop/enterprise_agent`
- 验证范围：本地纯核心、Sandbox、进程内 File MCP、Runtime 合同/预算/事件/提示、合成批次与静态检查
- 未使用真实业务日志、凭据、File Service Provider、模型 Provider 或外部对象存储

## 约 200 MiB 合成批次

命令：

```text
.venv/bin/python scripts/benchmark_log_evidence_scanner.py
```

首次运行在显式报告写入阶段发现 macOS `/var` 到 `/private/var` 的合法根路径别名被 Sandbox 误判为路径逃逸。已统一用解析后的 Sandbox 根做目标边界比较，并增加符号链接根路径回归测试。修复后批次结果：

| 指标 | 结果 |
|---|---:|
| 输入文件 | 20 |
| 单文件大小 | 10 MiB |
| 输入/完整扫描字节 | 209,715,200 / 209,715,200 |
| 逻辑行 | 1,602,750 |
| 物化次数 | 20 |
| 扫描 Tool 调用 | 1 |
| 候选/保留/省略 | 3,320 / 28 / 3,292 |
| 证据包大小 | 19,465 bytes |
| 扫描墙钟 | 25,260 ms |
| Python tracemalloc 峰值 | 264,316 bytes |
| 进程峰值 RSS | 28,426,240 bytes |
| 事件包含字面词/输入路径 | false / false |
| 报告显式选择/提交 | true / true |
| 合成 Delivery 状态 | PENDING |

本批次使用运行时临时目录生成异构 UTF-8 日志，结束后清理，未把约 200 MiB 输入提交到仓库。RSS 是进程级观测，包含解释器基线；tracemalloc 是 Python 分配观测，两者都不是容器级硬上限证明。真实 Provider、真实模型推理与真实 Delivery 尚未执行，不能把本地合成提交回执解释为生产交付成功。

## 最终检查

### 相关 pytest 与 Runtime 合同

```text
.venv/bin/pytest -q \
  backend/tests/test_log_evidence_scanner.py \
  backend/tests/test_python_job_sandbox.py \
  backend/tests/test_python_file_transfer.py \
  backend/tests/test_python_file_mcp_runtime_bridge.py \
  backend/tests/test_python_agent_runtime.py \
  backend/tests/test_runtime_http_client.py \
  backend/tests/test_agent_runtime_protocol_contract.py \
  backend/tests/test_test_suite_governance.py \
  backend/tests/test_mcp_meta_fidelity.py \
  backend/tests/test_agent_runtime_compose_security.py
```

结果：`174 passed in 20.34s`。该集合包含 CI 的 Python Runtime 合同组、Runtime v1.4 schema/hash 校验、File Bridge、预算、事件、提示、Sandbox 与测试分层治理。本变更未修改 Runtime v1.4 schema，因此没有生成文件变更；现有生成合同与事件 schema 校验通过。

CI 对应合同命令的独立结果：`22 passed in 5.20s`。

### 静态检查

受影响的 14 个 Python 文件执行 Ruff format check 与 Ruff check，通过；10 个受影响源码/脚本执行严格 mypy，通过：

```text
14 files already formatted
All checks passed!
Success: no issues found in 10 source files
```

仓库全量 `.venv/bin/ruff check .` 通过。

### Compose、OpenSpec 与差异

以下命令通过：

```text
docker compose config --quiet
openspec validate add-bounded-log-evidence-scanner --strict
git diff --check
```

OpenSpec 输出：`Change 'add-bounded-log-evidence-scanner' is valid`。

## 已知无关 baseline

`make test-fast` 运行到终点为 `1205 passed, 1 skipped, 246 deselected, 2 failed`。其中一项曾由本变更新增的派生 Tool 行内重复 `runtime_build_identity` 超出 v1.4 schema 引起；已移除重复字段，Runtime 身份继续由既有 `component_build_identities` 记录，随后相关集合 `174 passed`。

剩余一项是本变更未触及的既有断言：

```text
backend/tests/test_python_runtime_internal_architecture.py::
test_python_runtime_has_no_dynamic_plugin_or_runtime_registry
```

该测试期望动态 import 只有 `claude_agent_sdk` 与 `claude_code_sdk`，当前基线代码还包含既有的 `claude_agent_sdk._cli_version`。单独复跑仍以同一断言失败；本变更没有新增或修改这段 import，不在本 change 内放宽架构测试。

仓库全量 `.venv/bin/ruff format --check .` 报告 90 个未触及文件需要格式化；全量 `.venv/bin/mypy backend/app` 报告 16 个未触及文件共 70 个既有类型错误。受影响文件的定向 format/mypy 均通过；本 change 不批量格式化或修复无关模块。

## 未执行的真实环境验证

- 未调用真实模型 Provider、真实 File Service Provider、真实对象存储或真实 Delivery 通道。
- 未使用现场 200 MiB 日志；批次输入全部为运行时生成的合成 UTF-8 数据。
- 未构建或发布生产镜像，未创建真实 Agent/Business Application Revision，也未创建真实新 Job。

因此本 evidence 证明实现、合同、受控批次和静态边界，不证明生产部署或真实现场报告质量。发布后仍须按 `deployment.md` 用新 Revision、Publication 与新 Job 完成全链验证，不能以容器 healthy 替代。
