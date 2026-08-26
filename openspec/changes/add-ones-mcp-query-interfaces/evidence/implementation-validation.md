# ONES MCP 基础查询接口实现验证

验证日期：2026-08-26（Asia/Shanghai）

## 已验证实现

- 12 个新增只读 Tool 已使用共享代码契约进入 `ones-mcp` Registry 与平台
  `MCP_TOOL_MANIFEST`；既有 `ones_work_item_search` 与
  `ones_list_project_role_members` 保持兼容。
- 11 份新增 GraphQL 文档集中位于
  `services/ones_mcp_server/provider/graphql/documents/`，Operation 固定 Team
  路径、`t` 查询类型、变量构造和响应 Parser；Tool 输入不接受 URL、Header、
  Token、Team、GraphQL 文档或 Operation code。
- 迭代列表、工作项时间线和 Team 人员搜索使用固定 REST Operation；时间线
  GET 不发送 JSON body，项目角色成员 GET 保持既有 `{}` body 合同。
- 新 Tool 复用 Principal、Job/Publication 冻结、业务授权、一次 Credential
  refresh、Credential CAS/mark-used 和安全审计骨架；Provider 审计只记录固定
  Operation 摘要与数量摘要，不记录 GraphQL 文档、原始 Provider 响应或认证材料。
- 独立 Mock 仅使用 `MOCK-*` 合成项目、迭代、工作项、消息、人员和测试资产；
  架构测试禁止生产、Mock 和测试代码读取 `ones_mock/ones/`。

## 验证结果

- `openspec validate add-ones-mcp-query-interfaces --strict`：通过。
- ONES 聚焦 pytest（含测试分层治理）：109 passed。
- `ruff check .`：通过。
- `python -m compileall -q backend/app services/ones_mcp_server ones_mock`：通过。
- ONES 范围 mypy（`--follow-imports=silent`，38 个源文件）：通过。
- 全仓标准 mypy：未通过；当前基线在 document processing、file workspace、
  message bus 等非 ONES 模块有 68 个既有/并行变更错误，本 change 未修改这些
  错误点，ONES 范围无新增错误。
- `git diff --check`：通过。
- 根 Compose 与 `ones_mock/docker-compose.ones-mock.yml` 的
  `docker compose config --quiet`：均通过。
- `ones-mcp` 与独立 `ones-mock` 镜像重建并启动；两个容器均为 healthy。
- `ones-mcp` 容器内自身健康检查与经配置 Provider 地址访问 Mock 健康检查：
  均返回 HTTP 200。
- 运行中的 Mock 合成接口闭环：项目 1 条、迭代 2 条、测试库 1 条。

## 尚未验证

- Mock 通过只证明仓库内固定请求、Parser、安全边界和治理链路闭环，不证明当前
  真实 ONES 租户/版本兼容。
- 真实 ONES 验证需要经授权的只读环境，以新 Publication 和新 Job 依次探测项目、
  工作项类型、迭代、工作项、时间线和测试资产；只记录结果类别、数量、耗时与
  correlation，不记录 Token、原始业务正文或 Provider 原始响应。
- 本 change 不包含统计口径、统计聚合 Tool 或 Agent Skill；这些留给后续独立
  change，由用户在每次需求中提供可变统计定义。
