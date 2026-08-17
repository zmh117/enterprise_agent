# 06 部署与运维

默认 Compose 核心服务：PostgreSQL、RabbitMQ、Migrator、API、Admin Web、Worker、Python Runtime、`tool-mcp` 及渠道/交付 Worker；不再构建或启动 TypeScript Agent Runtime。

运维原则：

- Migrator 是唯一 schema writer；它依次执行 baseline migration、初始管理员 bootstrap 和 Runtime grants，业务服务只校验 schema head。
- 当前空库 head 为 `100`；只直接支持空库 baseline 或精确 legacy 042 adoption，部分 legacy head 必须先用旧镜像升到 042。
- 数据库升级和破坏性迁移前完成可恢复备份。
- 只重建受影响镜像，但验证完整 Runtime -> MCP -> Resource -> Delivery 链路。
- `.env` 不存真实 Secret；密钥文件位于仓库外且权限受限。
- 容器 healthy 不是业务验收，必须检查 Job、Tool Call、Runtime Event 和 Delivery。

常用检查：

```bash
docker compose config --quiet
docker compose ps
docker compose logs migrator tool-mcp agent-worker
```

操作细节见 [空库手册](../../operations/schema-baseline-bootstrap.md) 和 [Legacy 042 升级手册](../../operations/schema-baseline-upgrade.md)。
