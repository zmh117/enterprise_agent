# 当前部署与运维

## Compose 边界

当前 Compose 包含 PostgreSQL、RabbitMQ、API、Admin Web、DingTalk Runtime、Python workers、TypeScript Agent Runtime、ONES/Data MCP、MinIO 和 Delivery/Attachment 服务。

- migration 由 one-shot `migrator` 独占执行，当前 schema head 为 `040`；
- `agent-runtime` 非 root、只读文件系统、独立 Master Key/DB role/Provider egress；
- `agent-worker` 是纯 Python 镜像，没有 Master Key、Node/Claude CLI 或 Provider egress；
- API 和 MCP Server 仅挂载各自必须的 Secret；
- `mcp-control` 为内部网络，`provider-egress` 只授予必须访问外部 Provider 的服务。

## 版本基线与约束

| 组件 | 版本 |
| --- | --- |
| Node.js | `22.x` / Debian 13（`node:22-trixie-slim`） |
| TypeScript Runtime | `0.1.0` |
| Claude Agent SDK TS | `0.3.226` |
| Claude CLI | `2.1.226` |
| Runtime protocol | `1.0` |
| MCP Server SDK | `2.0.0` |

## 基础验证

```bash
docker compose config --quiet

cd agent-runtime
npm run check:contracts
npm run preflight:static
npm run lint
npm run typecheck
npm test
npm run build

cd ../frontend
npm run lint
npm run typecheck
npm test
npm run build

cd ..
.venv/bin/pytest
openspec validate --all --strict
git diff --check
```

真实部署必须在 Runtime 容器身份和 mount 下执行 `npm run preflight`，验证精确版本、数据库逐列 grant 和 Secret 文件权限。

## Readiness

- Runtime `/health`：只证明进程；
- Runtime `/version`：报告 runtime/protocol/SDK/CLI 精确版本；
- Runtime `/ready`：只检查 DB 与 Master Key，不调用模型或 MCP；
- API `/api/ready`：聚合 schema、RabbitMQ、Master Key、Runtime 和治理 Resource 状态。

## 管理方式

前端恢复 Agent Publication 和 Business Application 工作台；数据库/Redis/Loki 等 Data MCP Resource 的部署基础配置仍由受控 CLI/部署 Manifest 管理。前端不提供任意连接、Secret、SQL、URL 或脚本编辑器。

所有 Web 写请求携带 Session、CSRF、`expected_revision` 和 `Idempotency-Key`。冲突必须刷新比较，不能静默覆盖。

## 切换状态

- 已实现：Runtime、Worker client、MCP Publication、Agent/Application 控制面与前端、部署静态边界、预检和测试。
- 待环境验收：指定 Application Publication 的真实 canary、测试环境默认切换、真实 Claude/DeepSeek → ONES/DB/Redis/Loki、完整钉钉 Delivery。
- 待用户确认：生产维护/观察窗口、旧 Python Runtime 删除、生产门禁关闭和 OpenSpec 归档。

完整 canary、在途 Job、取消、回滚、观察和升级步骤见 [TypeScript Agent Runtime 切换与运维手册](../typescript-agent-runtime-cutover.md)。
