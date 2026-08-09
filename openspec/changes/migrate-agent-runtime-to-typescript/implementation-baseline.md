# TypeScript Agent Runtime 迁移实施基线

记录日期：2026-08-09

## 起点与回退边界

- 实施分支：`mcp_dev`
- 本变更提案基线：`3bc8dde`（`docs(openspec): propose TypeScript agent runtime migration`）
- MCP 平台替换基线与代码回退点：`aa5c8ce`（`feat: replace legacy API platform with MCP runtime`）
- 迁移必须基于当前 `mcp_dev` 演进；不得从 `master` 恢复已经退役的 API/Internal Platform、Capability、Handler 或旧 Resource Composition 实现。
- 回退仅允许在 Application Publication/环境迁移 gate 上切回已冻结的 Python Runtime 版本，不能用运行中 attempt 自动 fallback，也不能复活旧 API/Internal Platform。

## MCP 前置变更状态

前置变更 `simplify-platform-with-mcp` 当前实现任务完成 65/71，尚未归档。以下真实环境/破坏性验收仍未完成：

- 10.2：可丢弃环境从空 schema 创建 Secret/Resource/Deployment 与用户重新验证。
- 10.3：空数据后的登录、Session、钉钉 Challenge、ONES 重新验证、默认 Team 与渠道身份。
- 10.4：Worker 到 ONES/Data MCP 的 ONES/DB/Redis/Loki 真实只读链路、精确 allowlist、取消发布和凭据轮换。
- 10.5：Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → MCP → Delivery 完整真实链路。
- 10.6：重启、Token 过期、Provider 拒绝、Resource generation 失败和 Delivery retry 的失败关闭审计。
- 10.7：用户明确安排生产维护窗口后的不可恢复清理。

当前验收还发现 MCP Tool Publication 缺少正式写入/发布控制面，`DENIED` provenance 和真实 Claude/ONES/DingTalk 链路也没有形成完整证据。本迁移会补齐控制面和 Runtime 链路，但不会提前勾选这些真实验收项。

## 已确认的 Runtime 版本约束

- 官方 npm registry 在实施日返回的最新非 prerelease `@anthropic-ai/claude-agent-sdk` 为 `0.3.226`。
- 包声明的最低 Node.js 版本为 `>=18.0.0`；本仓库 Runtime 使用 Node.js 22 LTS 主版本，2026-08-09 验收镜像实际解析为 `22.23.1` / Debian 13。
- 当前基础镜像标签是用户明确选择的 `node:22-trixie-slim`，它会随 Node 22 patch 更新；生产发布前仍需明确决定是否改为精确 patch/digest，以满足可复现构建要求。
- 生产构建和启动阶段禁止动态安装 SDK/CLI，也禁止使用 `latest`、范围版本或 prerelease tag。

## 未完成门禁

- 前置变更归档后，才能执行任务 1.7 的 main spec/delta 冲突复核。
- 真实 Provider、ONES、Data MCP、DingTalk 和生产切换必须分别形成测试证据。
- 生产迁移与最终归档必须等待用户明确验收；本文件不构成验收或切换授权。

## 2026-08-09 本地验收证据

- 验收版本：Node.js `22.23.1` / Debian 13、Runtime `0.1.0`、协议 `1.0`、`@anthropic-ai/claude-agent-sdk` `0.3.226`、CLI `2.1.226`；`preflight:static` 与容器内 deployment preflight 均通过。
- TypeScript Runtime：lint、typecheck、28 个 unit/contract/security/HTTP 测试、contract generation check 和 build 通过；`npm audit --omit=dev --audit-level=high` 为 0 个漏洞。
- 生产 Runtime 镜像构建成功，验收镜像 digest 为 `sha256:f8421d3e93bb10f907ca63ed2b69370bdd41338d626d687135b8a362703c9a45`；实际用户为 `uid=1000(node)`，根文件系统只读，无 Python/pip，Compose 限制和 ONES/Data MCP 私有网络健康检查通过。
- 可丢弃空 schema Compose 验收首次发现 `mcp_service_grants.sql` 仍引用 migration `040` 删除的 5 个表，修复并增加回归后 migration head `040`、service grants、ONES/Data MCP 与 Agent Runtime 全部成功/healthy。
- Python 后端：Ruff check/format、Mypy `backend/app` 268 个源文件、340 个测试通过；16 个需要外部 PostgreSQL、RabbitMQ、Provider 或真实凭据的 opt-in 集成测试跳过。Migration head 为 `040`。
- 当前主 Compose 首次启动暴露了缺失部署 Secret，以及通用 Worker 容器误初始化模型探针和默认模型连接的边界问题；仅创建缺失的内部 Secret 后，将探针 Token/默认连接引导限制到 API 控制面，并增加 Compose 与启动装配回归。现 6 个 Worker 均运行，调度 Worker 心跳健康，且所有 Worker 均未挂载或声明模型探针 Token。
- 前端：lint、typecheck、27 个 unit 测试和 production build 通过；浏览器完成登录、权限导航、Agent/Application 管理、375x812 窄屏、键盘焦点和非颜色状态验收。
- OpenSpec：`openspec validate --all --strict` 为 85 passed / 0 failed；`git diff --check` 通过。
- 本次临时环境的容器日志、PostgreSQL data dump 和前端产物对挂载 Secret 明文的匹配数均为 0；RabbitMQ payload、API、trace、真实 Runtime ledger/Tool provenance 尚未形成，不能据此勾选全介质扫描。
- Docker Scout OS CVE 扫描因本机未登录 Docker ID 无法执行；npm 生产依赖审计已通过。
- 非阻断告警：Starlette TestClient deprecation warning；前端主包约 678 kB，超过 Vite 500 kB 建议阈值；基础镜像 tag 为浮动 Node 22 patch。将严格 Mypy 临时扩展到非门禁范围 `services/` 与 `scripts/` 时仍有 71 个既有错误，主要来自 MCP 2.x 未类型化 decorator/provider adapter；正式门禁范围 `backend/app` 通过。
- 仍需真实环境证据：指定 Application canary/生产窗口、Claude/DeepSeek 与 ONES/DB/Redis/Loki MCP、完整钉钉链路、全介质敏感数据扫描；这些项目不得由本地 mock、健康检查或静态配置替代。
