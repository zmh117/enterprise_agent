## 1. 恢复钉钉身份 Schema 不变量

- [x] 1.1 新增唯一的前向 migration 130，以幂等方式恢复钉钉企业 + Staff ID、内部用户 + 钉钉企业两个唯一索引，不修改 migration 100/126。
- [x] 1.2 增加 fresh SQLite、从 head 129 升级以及已有重复身份时失败关闭的 migration 测试，确认失败不会登记 head 130 或删除业务数据。
- [x] 1.3 更新受 migration head 影响的静态事实与测试期望，确认 PostgreSQL 路径保留既有索引且 SQLite/PostgreSQL 结果语义等价。

## 2. 修复默认 Webhook 种子 Publication 图

- [x] 2.1 同步 `local_seed.sql` 中默认 Webhook Trigger snapshot 和列级 Agent revision/config hash，使其精确引用当前 seeded Agent Publication，保持 Webhook revision config hash 不变。
- [x] 2.2 增加默认种子跨 Publication 完整性测试，直接断言 Agent publication ID、revision 和 hash 一致，并保留不一致时 Dispatcher 失败关闭的覆盖。
- [x] 2.3 复验三条 Webhook/Channel 原失败链路，确认 firing 创建且只创建一个固定 Agent Job、resolved 仍被忽略、不同事件仍隔离 Session。

## 3. 同步 Python Runtime 架构契约测试

- [x] 3.1 将 `claude_agent_sdk._cli_version` 加入固定动态导入允许列表，继续拒绝非字面量导入、模块扫描、entry points 和 Runtime Registry。
- [x] 3.2 增加固定 SDK CLI 版本读取与私有版本模块不可用时 executable 回退测试，不改变 SDK 选择或 Runtime 生产实现。

## 4. 回归与交付验证

- [x] 4.1 运行原 5 条失败测试及 DingTalk identity migration、Webhook、Channel、Python Runtime 定向回归，确认全部通过。
- [x] 4.2 运行 Ruff、受影响 Python 模块 Mypy、完整 backend 测试和 `git diff --check`，确认原基线 5 条失败清零且没有新增失败。
- [x] 4.3 运行 `docker compose config --quiet` 与 `openspec validate repair-backend-baseline-regressions --strict`，记录本地验证不代表真实 DingTalk、Webhook 外部投递或生产数据库 migration 验收。
