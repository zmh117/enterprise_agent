## Why

完整 backend 回归长期保留 5 条失败：默认 Grafana Webhook 的冻结 Agent Hash 与当前默认 Agent Publication 不一致、SQLite 在 ONES 身份迁移重建表后丢失钉钉身份唯一索引、Python Runtime 架构测试未同步合法的固定 SDK 版本导入。这些失败掩盖真实回归，其中前两项还会分别阻断新建本地环境的默认 Webhook 和削弱 SQLite 身份一致性约束，应在独立 change 中恢复既有规范与实现的一致性。

## What Changes

- 重新生成默认 Webhook Trigger 种子快照中的 Agent revision/config hash，使其与同一份种子中的默认 Agent Publication 完整一致，并增加跨 Publication 种子完整性回归。
- 新增前向 migration，恢复 SQLite 表重建时丢失的两个钉钉身份唯一索引；对既有重复数据失败关闭，不修改已发布 migration。
- 更新 Python Runtime 架构测试的固定动态导入允许列表，继续禁止插件发现、动态 Registry 和非固定模块导入，并覆盖 CLI 版本读取回退。
- 运行 5 条原失败测试、相关领域回归和完整 backend 测试，确认不存在新的失败。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`：明确表重建 migration 必须恢复仍生效的约束/索引，以及版本控制下的内置初始化 fixture 必须保持跨 Publication 冻结引用自洽；不改变业务 API 或运行协议。

## Impact

- 数据库：新增一个无破坏性的前向 migration；不修改 migration 100 或 126，不新增表或字段。
- 本地种子：更新默认 Agent/Webhook Publication 的派生完整性事实，不修改 Secret、public ID、路由、工具集合或授权。
- Runtime 测试：只调整固定 SDK 兼容导入的架构断言及回退覆盖，不引入插件机制或新依赖。
- 外部协议：无 API、消息、Webhook、Agent Runtime 或数据库字段协议变更。
