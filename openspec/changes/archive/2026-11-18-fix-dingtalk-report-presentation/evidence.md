# 本地验证记录

日期：2026-11-04。测试仅使用合成数据、内存 SQLite 和假 Provider 传输。

## Prompt、上下文与初轮分片回归

```bash
.venv/bin/pytest -q \
  backend/tests/test_delivery_outbox_chunk_idempotency.py \
  backend/tests/test_mcp_tool_runtime.py \
  backend/tests/test_python_agent_runtime.py -x
```

结果：153 passed。验证所有支持的钉钉路由注入格式标识、其他渠道隔离、目标字段不投影、
Prompt v8 与完整明细约束，以及初轮分片和幂等测试。

## 最终投递、拒绝路径与协议回归

补充损坏历史摘要、系统说明恢复和 Markdown/emoji 传输测试后运行：

```bash
.venv/bin/pytest -q \
  backend/tests/test_delivery_outbox_chunk_idempotency.py \
  backend/tests/test_delivery_outbox_atomic_terminal.py \
  backend/tests/test_delivery_outbox_dispatcher.py \
  backend/tests/test_dingtalk_delivery.py \
  backend/tests/test_file_version_delivery.py \
  backend/tests/test_runtime_http_client.py \
  backend/tests/test_agent_runtime_protocol_contract.py \
  backend/tests/test_attachment_worker_contract.py
```

结果：134 passed。两轮有重复用例，不能将两个数字简单相加作为独立用例数。

重点验证：

- 段落优先、换行兜底、超长正文硬切；CRLF、Unicode、空白和 20 条完整长标题原样保留。
- 新分片含 `part x/y` 不超长度；跨两位数片数也满足上限。
- 修改默认长度后重试仍沿用原计划，跳过成功片；历史无计划任务恢复原固定字符切法。
- 未知计划、缺少历史长度、损坏摘要、hash 漂移在再次发送前失败；失效 claim 不能写入计划。
- 系统说明使用相同的稳定分片机制；钉钉假传输接收到的 Markdown 和 emoji 与分片正文一致。
- 原有文件投递、投递终态、并发 Dispatcher 与 Runtime 协议测试通过。

## 静态与文档检查

- 6 个修改的生产 Python 文件：mypy 通过。
- 6 个生产文件及 4 个测试文件：Ruff lint / format check 通过。
- `git diff --check` 通过。
- `openspec validate fix-dingtalk-report-presentation --strict` 通过。
- `.venv/bin/python scripts/check_markdown_links.py` 返回 `MARKDOWN_LINK_CHECK_SUCCEEDED`。

## 尚未验证的边界

未重建或重启运行中服务，未访问生产消息或发送真实钉钉消息，未运行真实模型/Provider
和钉钉客户端视觉验收，也未验证目标生产 PostgreSQL 上的并发行为。本地测试通过不代表
生产已经生效或模型必然遵循排版指引。

相关更新服务与验收步骤见[运维说明](../../../docs/runbooks/dingtalk-report-presentation.md)。
主规格尚未同步或归档；本记录不代表服务已经部署或生产验收通过。
