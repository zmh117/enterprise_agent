# 2026-09-08 消息恢复与分页正确性验收

## 范围与消息恢复

- 用户确认部署在本机，并确认「Agent 应用重新发布就好了」。
- 本次初查主 Compose 栈容器不存在，但数据卷保留；复用现有配置与数据启动主服务，没有清空数据、修改权限或直接改写 Publication。
- 仅读取去敏状态字段：2026-09-07 09:45 UTC 的 `channel_ingress_event` 为 `REJECTED / mcp_tool_schema_drift`，未生成 Job；09:50、09:52 UTC 的后续事件均为 `JOB_CREATED`，对应 Job 均为 `SUCCEEDED`。这与用户确认的重新发布恢复一致，不归因为模型不回复。
- 2026-09-08 检查渠道运行状态为 `CONNECTED`，无错误码。API、Agent Runtime、渠道分发及 DingTalk Runtime 均运行。
- 本次不改变工具 Manifest/schema。更新前后契约指纹均为 `ff7140bf4c0ed55ea4bc60647b039a06b1cb6891ecb839fe4584f814a22dd4bb`，无需为这轮分页实现修复再次发布应用。

## 修复与拒绝边界

- Oracle 首页对空游标显式使用 `IS NULL` 分支；后续页保留原始表名作为排他下界，避免 quoted mixed-case 表名被强制转大写。新增测试执行实际 SQL 谓词，仅用 SQLite 适配 ROWNUM 并模拟 Oracle 空字符串转 NULL，验证 51 表按 50 + 1 + 0 返回。该测试在修复前失败。
- Redis 不把 COUNT 当作响应条数上限。超额批次分多页返回，记录原 provider cursor、已返回偏移和完整批次摘要；批次读完前不推进 provider cursor，包括上游已返回 `0` 的末批。该测试在修复前失败。
- 批次重读验证规范排序后的键集合及下一 provider cursor；变化返回 `mcp_pagination_cursor_stale`。空批次的非零 provider cursor 继续扫描，不误判结束。
- Cluster 使用 redis-py `ClusterNode` 和逐主节点的标量 SCAN。节点耗尽后才移动到下一主节点；拓扑摘要变化时在 SCAN 前拒绝。公开 cursor 不含键正文或节点地址；旧的节点字典位置无效时要求从第一页重查。
- 对非法数值/结构、跨 Job、用户、应用、授权 hash、Snapshot hash、过滤条件、页大小和资源修订的 cursor 拒绝复用；授权/资源变化不会触发新的上游 SCAN。
- Redis 客户端使用后关闭。TLS 验证策略保持不变，关闭验证的既有显式配置统一使用 redis-py 支持的 `"none"` 表示，避免驱动类型契约漂移。

## 验证证据

- 最终执行 `RUN_REDIS_PAGINATION_INTEGRATION=1 .venv/bin/pytest -q --durations=10 backend/tests`：**1786 passed、30 skipped、2 subtests passed**，294.79 秒。此次完整运行包含最终新增边界用例和实际 Redis 单机/Cluster 验收。
- `.venv/bin/ruff check .`、`.venv/bin/mypy backend/app`（408 个源文件）、`docker compose config --quiet`、严格 OpenSpec 校验、Markdown 链接检查、`git diff --check` 均通过。变更文件格式检查中 10 个文件通过，资源验证器现有 Loki selector 格式段仍被 formatter 提示；该段不在本次改动中，不扩展为无关格式重写。
- `RUN_REDIS_PAGINATION_INTEGRATION=1 .venv/bin/pytest -q backend/tests/test_redis_scan_pagination_integration.py`：8 项通过。Redis 7.4 单机与三主节点 Cluster 分别验证 0/50/51/501 个合成键，逐页不超限、完整遍历、稳定数据无重复。使用专用临时容器和合成命名空间，不连接业务 Redis。测试已加入 CI，并作为 Runtime 镜像构建前置检查；尚未声称远端 CI 已执行。
- 已重建并更新本机 `tool-mcp`，镜像 `sha256:8a2771a239cfa34f6bd0962cbf2a566fe850e59928396a74d21a0a99e7067c6a`，容器 Healthy，`/health` HTTP 200。
- 容器内 5 个受影响生产源文件的 SHA-256 与工作区逐项一致，确认实际部署了本次实现，而不只是完成镜像构建。
- 在更新后的运行容器内使用实际 `DirectReadOnlyToolExecutor`、公开 cursor 和 redis-py 8.1.0 访问专门创建的隔离 Redis：501 个合成键，页大小 7 返回 90 页、页大小 50 返回 14 页，均完整且无重复。验收后删除该临时容器及其合成数据；不涉及用户业务数据。此项是部署后适配器验收，不是新建真实用户 Job 的模型端 E2E。

## 保留限制

- 当前 tool-mcp 更新前后均缺少合规 Oracle Instant Client 19c，状态 `thin_only`；平台要求 Oracle Thick/19c，因此真实 Oracle 查询仍不可用。本次 SQL 语义回归不是 Oracle 实例连接/目录验收，也没有绕过该限制或下载未经批准的客户端。
- Redis SCAN 不提供快照语义；数据写入、删除、过期或迁槽仍受 Redis 原生一致性语义约束。批次摘要只对未读完批次的变化明确拒绝，不能承诺动态数据 exactly-once。
- Cluster 验收覆盖已有 gateway 能力，没有扩大已发布治理资源的 provider 契约或自动发布额外资源。
- 不修改模型、业务权限、Secret 或数据库 Schema；未提交代码、未归档 OpenSpec。
