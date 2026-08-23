# 06 部署与运维

默认 Compose 定义 PostgreSQL、RabbitMQ、Migrator、MinIO、API、Admin Web、
`dingtalk-runtime`、Agent/Dispatch/Channel/Webhook/Delivery Worker、Python Runtime、
`tool-mcp`、`ones-mcp`、File Service/File Worker、Docling 与 File Processing Worker；
不再构建或启动 TypeScript Agent Runtime。Admin Web 仍要求
`FEATURE_WEB_ADMIN=true`，否则容器入口退出。

运维原则：

- Migrator 是唯一 schema writer；它依次执行 baseline migration、初始管理员 bootstrap 和 Runtime grants，业务服务只校验 schema head。
- 当前空库顺序执行 `100..119`，最终 head 为 `119`。精确 legacy 042 adoption 必须先用
  单独 baseline-only head-100 build；当前 checkout 会拒绝直接 adoption。部分 legacy
  head 必须先用旧镜像升到 042。
- 数据库升级和破坏性迁移前完成可恢复备份。
- 只重建受影响镜像，但验证完整 Runtime -> MCP -> Resource -> Delivery 链路。
- `.env` 不存真实 Secret；密钥文件位于仓库外且权限受限。
- 容器 healthy 不是业务验收，必须检查 Job、Tool Call、Runtime Event 和 Delivery。

常用检查：

```bash
docker compose config --quiet
docker compose ps
docker compose logs migrator tool-mcp ones-mcp file-service agent-worker
```

操作细节见 [空库手册](../../operations/schema-baseline-bootstrap.md) 和 [Legacy 042 升级手册](../../operations/schema-baseline-upgrade.md)。
