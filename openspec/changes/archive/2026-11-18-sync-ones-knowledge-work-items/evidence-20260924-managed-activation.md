# 受管 ONES 内容激活：代码与合成验收

- 已实现候选索引逐点验证后，以同一平台 PostgreSQL 事务核对启用状态、绑定修订、启动时资源基线、已发布资源配置钉住值、候选内容基线，切换文档 current 修订、KB 收录、关系解析、不可变资源修订、发布指针与运行水位。资源范围变化、管理员草稿/停用、内容基线冲突均阻断激活；新 KB 无资源时只激活内容，不首次发布或授权。
- 迁移 146 仅增加同步绑定的资源钉住事实；启用时拒绝外部内容 PostgreSQL，配置重设清除钉住值并停用；自动换版事务内刷新当前钉住值。没有运行 Migrator 或更新本机服务。
- 合成测试覆盖内容与发布一起成功、无变化零建索引/零发布、事务中断回滚、提交后回执丢失幂等、草稿/停用冲突、类型迁移后的零成员 READY 代际、检索固定旧版本在切换后失败重试，以及异库启用拒绝。MCP 本人授权与 120 秒预算使用既有定向测试回归，本次未改在线检索实现。
- 受管每小时入口已实现：原 `collect_ones_knowledge` 管理绑定和启停，新 `sync_ones_knowledge` 负责状态、单轮和 daemon；持久阶段先恢复，默认环境开关关闭，Compose 为 `knowledge/sync.compose.yml` 可选 overlay。整轮持有独立写者锁，并在锁内复查到期时间，避免两个容器在同一 tick 重复开始。定时周期固定 3600 秒；禁用、SIGTERM 在分页/块/向量批次边界有界停止，错误仅落固定码。没有实际启用或连接真实 ONES。
- 定向回归：`147 passed, 4 skipped`（候选、替换、采集、向量、受管流水线与 schema）；扩展知识库回归 `323 passed, 1 skipped`（类型、关系/稀疏文本、分块、混合索引、资源、授权、MCP、可读性与预算）；schema 基线 `56 passed`。新增测试已登记层级；`make lint`、`make format-check`、`make typecheck`、Markdown 链接、Compose 配置、严格 OpenSpec、`git diff --check` 通过。跳过项及合成 SQLite/内存 Qdrant 不代表隔离 PostgreSQL、真实 Qdrant 或真实 ONES 验收；8.2–8.4、10.x 仍待相应环境证据。
