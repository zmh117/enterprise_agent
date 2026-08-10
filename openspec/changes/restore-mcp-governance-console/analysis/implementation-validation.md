# 治理控制台恢复验证记录

验证日期：2026-08-10

## 已验证命令

- `.venv/bin/python -m pytest -q backend/tests`
  - 结果：`371 passed, 16 skipped, 1 warning`
  - 唯一 warning 为 Starlette `TestClient` 的依赖弃用提示，不是本变更回归。
- `cd frontend && npm run typecheck && npm test -- --run && npm run build`
  - 结果：TypeScript 类型检查通过；`7` 个测试文件、`27` 个测试通过；Vite 生产构建通过。
  - 构建仅报告主 chunk 大于 500 kB 的性能提示，不影响正确性；后续可按页面继续拆分 lazy chunk。
- `cd agent-runtime && npm test`
  - 结果：`27` 个不监听端口的测试通过；HTTP Runtime 测试因当前沙箱禁止监听 `127.0.0.1`，报 `listen EPERM`。
  - 该环境限制不能声明为 Runtime HTTP E2E 通过，也不是本次治理前端恢复产生的业务失败。
- `cd agent-runtime && npm run build`
  - 结果：TypeScript Runtime 构建通过。
- `openspec validate restore-mcp-governance-console --strict`
  - 结果：通过。
- `git diff --check`
  - 结果：通过。

## 已恢复且有回归证据的链路

- 登录 Session、CSRF 与权限感知 Shell。
- 多 Agent 与多 Application 现有治理工作区入口。
- 用户、角色、Application 使用授权与安全身份摘要。
- 未绑定钉钉候选列表、现有人员选择、初始角色与历史身份恢复入口。
- 受信 MCP Server、Tool Publication、精确 Resource Deployment 选择。
- Database、Redis、Loki 服务端白名单表单与 Credential ID 到内部 Secret Ref 的服务端解析。
- Credential 创建、轮换、停用的浏览器安全投影。
- 钉钉企业与应用连接器新建、编辑、启停、测试、重启；浏览器只选择 Credential ID。
- 受控 Debug Job、管理员范围化 Job 历史、MCP/Delivery 证据与受控取消。
- 权限范围化 Dashboard 聚合与当前 MCP 数据链路。

## 仍未完成，禁止误报

- 两个前置 OpenSpec change 的最终同步/归档与真实环境验收。
- 角色数据范围和有效权限模拟。
- 所有管理 mutation 的统一 expected revision、幂等重放、冲突码与审计中间件。
- 管理员 Session 历史、完整 Connector/Trigger/Delivery 对象治理及全部前端组件级 contract 测试。
- 干净 Compose、真实 Database/Redis/Loki、钉钉、ONES 与 TypeScript Runtime 的端到端验收。
- OpenTelemetry 实施；本 change 只保留传播点和敏感字段禁采边界。
