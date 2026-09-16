# 本地验证及部署边界

日期：2026-09-16。

## 已实现

- 扫描器版本升级为 `log-evidence-v2`。字面词按 `casefold()` 去重并保留首次拼写/顺序，完全重复也接受；原始数组数量、字符数和 UTF-8 总字节预算保持不变。
- 词项 Schema 不再拒绝完全重复项，参数及工具描述明确物化来源、`inputs/` POSIX 相对路径和 Windows 宿主机注意事项。裸文件名、绝对路径、反斜杠及越界路径仍拒绝，不自动补全路径。
- 扫描器的已知错误码经固定中文映射进入文件桥结果、SDK 安全事件和 Runtime 工具失败投影；输入/路径/完整性/容量等确定性失败为 `NEVER`，读写 I/O 为 `TRANSIENT`。未知码保持通用安全回退，其他工具和权限拒绝行为不变。
- 普通工具主账及前端已有摘要链路无需扩展字段，保持只显示固定安全错误信息，不增加实际文件名、词项、正文或动态异常文本。

## 自动验证

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest backend/tests/test_log_evidence_scanner.py backend/tests/test_python_file_mcp_runtime_bridge.py backend/tests/test_python_agent_runtime.py backend/tests/test_runtime_http_client.py backend/tests/test_mcp_tool_runtime.py -q --tb=short
```

结果：210 passed。

随后追加工具主账持久化回归并执行：

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest backend/tests/test_python_agent_runtime.py -k scanner_failure_reaches -q --tb=short
```

结果：2 passed。输入错误和路径错误均完整进入工具主账的安全摘要；工具保持 FAILED，合成 Agent 完成有界诊断时 Job 仍为 SUCCEEDED。

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest backend/tests/test_python_job_sandbox.py backend/tests/test_tool_response_summary.py backend/tests/test_agent_runtime_protocol_contract.py backend/tests/test_python_runtime_internal_architecture.py -q --tb=short
```

结果：62 passed。三组共 274 项通过。

覆盖大小写/完全重复/Unicode casefold、证据幂等复用、原始重复词数量与字节超限、裸文件名及 Windows 反斜杠路径、未物化输入、真实 SDK 内存 MCP 连接、标准 SDK 对象事件、伪造错误载荷安全回退、工具失败持久化、Job 成功语义及原有沙盒/协议边界。

受影响 7 个 Python 文件的 Ruff 检查和格式检查通过；4 个改动源码的 `mypy --follow-imports=silent` 通过；`git diff --check`、`openspec validate harden-log-evidence-tool-inputs --strict` 和 `docker compose config --quiet` 通过。

## 尚未验证或执行

所有输入、文件和模型结果均为合成数据；SDK 内存连接不等于真实模型或远端 File Service/对象存储验收。本轮未读取现场日志或原始业务消息，未调用真实 Provider，未部署、发布或提交代码，未在 Windows 主机重新执行现场 Job。

## Windows 部署后验收

1. 使用同一构建更新相关服务镜像并通过现有构建身份检查，不只拉取代码后继续运行旧 Runtime 镜像。无数据库迁移、无远端 MCP 工具清单变更，也不回写历史 Job。
2. 用新 Job 确认扫描器版本为 `log-evidence-v2`，实际已物化 LOG 的路径带 `inputs/`。
3. 合规大小写重复词应成功扫描；裸文件名仍应明确返回 `log_evidence_path_invalid` 和路径纠正提示。固定预算不提高，非法路径不自动补前缀。
4. 核对普通运行记录保留具体错误码，不再把这些已知扫描错误统一显示为 `runtime_tool_failed`。旧 Job 原有泛化错误不会自动修补。
5. 完整字节扫描、保留证据数与模型语义理解仍是不同概念；不能以 Job 成功推断每一行已被模型理解。真实验收完成后再决定是否归档本变更。
