## 1. OpenSpec 前置对账

- [x] 1.1 已确认 `establish-schema-baseline-and-organize-docs` 完成语义同步并归档，且 canonical `platform-operations` 已包含最终 baseline `100`、精确 legacy `042` adoption、失败关闭与 adoption-only rollback Requirement
- [x] 1.2 将本 change 的 delta 与更新后的 canonical Requirement 逐项对账，消除标题漂移、重复 Requirement 或语义冲突，并运行相关 OpenSpec strict validation
- [x] 1.3 重新确认当前实现、测试和目标部署的 schema generation，分别记录 `Confirmed-current`、`Documented-intent` 与待部署状态，不使用旧验证快照替代现场检查

## 2. Runtime Config Definition 幂等对账

- [x] 2.1 先增加失败测试，覆盖相同 definition 重复对账不改变 revision、`updated_at`、聚合版本和配置审计
- [x] 2.2 实现 definition 规范化与显式 `created`／`updated`／`unchanged` reconciliation result，稳定处理默认 JSON、适用服务集合、布尔、枚举、描述和状态
- [x] 2.3 将 repository upsert 改为 expected-revision 条件更新；对插入唯一键竞争和更新冲突执行有界重读，保证每个真实变化最多递增一次 revision
- [x] 2.4 让 registry 和显式管理同步返回 created/updated/unchanged 汇总，并只在真实变化时记录不含敏感值的同步审计
- [x] 2.5 增加 SQLite 与 PostgreSQL 并发 reconciliation 测试，证明最终唯一记录、语义一致、无重复 revision 递增

## 3. 收紧读取与初始化边界

- [x] 3.1 先增加 definition GET、snapshot 和 ready diagnostics 的零写入回归，比较 definition revision、`updated_at`、配置审计和数据库写入结果
- [x] 3.2 从 definition 列表 GET、snapshot builder 和 ready diagnostics 移除隐式 ensure/sync，只保留 schema head 通过后的受控进程初始化与显式管理员同步
- [x] 3.3 为缺失内置 definition 增加稳定的 missing-definition／degraded 诊断，确保只读路径不自我修复且不泄漏 Secret、DSN 或原始配置值
- [x] 3.4 覆盖管理权限、重复 GET、重复 snapshot、服务重复初始化和初始化失败路径，验证读取响应与审计边界

## 4. 修正聚合 Runtime Config 版本

- [x] 4.1 先增加高 revision definition 存在时更新低 revision value 的失败测试，证明现有 `max(revision)` 会掩盖真实变化
- [x] 4.2 将聚合 revision 改为覆盖 definition、value 与相关 Secret metadata 的稳定聚合值，并保留脱敏 effective content hash 作为内容身份
- [x] 4.3 验证真实创建、更新、禁用或 Secret metadata 变化会改变聚合版本，而 no-op reconciliation、GET 和重复 snapshot 保持 revision/hash 不变
- [x] 4.4 更新 API／运行状态文档与调用方测试，明确聚合 revision 是不透明令牌，不依赖切换前后的具体数值且不得包含 Secret 明文

## 5. Baseline Adoption 运维与验证

- [x] 5.1 实现只读 baseline adoption preflight 入口，验证 legacy ledger/checksum、schema/comment fingerprint、关键数据计数 digest、目标 baseline 和 migrator build，且不得创建或修改 ledger/adoption 表
- [x] 5.2 实现 adoption 后只读 verify 入口，核对唯一 marker/metadata、SchemaHeadValidator、关键数据计数、配置 revision 摘要和 readiness 所需状态，并对输出执行敏感信息脱敏测试
- [x] 5.3 编写中文 Runbook，固定“停止业务写入、逻辑备份并核验、目标镜像 preflight、one-shot adoption、verify、启动服务、最小闭环”的顺序
- [x] 5.4 在 Runbook 中区分 adoption-only 受控 rollback 与已执行后续 migration 的逻辑备份恢复，禁止手工修改 ledger，并要求成功验收前保留旧镜像、旧卷和备份
- [x] 5.5 在 disposable PostgreSQL 副本演练精确 `042 -> 100`、重复 adoption、漂移拒绝、验收失败和 adoption-only rollback，验证业务计数、配置 revision 摘要及 schema/comment 不变量
- [x] 5.6 将当前 Compose 数据库的真实 adoption 保持为独立部署授权步骤；普通 apply、单元测试和集成测试不得自动修改该数据库

## 6. 完整验证与交付

- [x] 6.1 运行受影响的 migration、runtime config、platform config API、readiness 和敏感信息回归测试，并区分 focused validation 与仓库既有失败
- [x] 6.2 使用项目 PostgreSQL 集成环境运行 adoption、并发 reconciliation、零写入读取和 revision/hash 稳定性测试
- [x] 6.3 运行 Ruff、mypy、后端全量测试、Compose config 与受影响服务镜像构建；不以容器 healthy 代替 migration 和应用闭环证据
- [x] 6.4 运行 `openspec validate --all --strict`、检查未完成任务、`git diff --check` 和工作区范围，确认未修改其他 active change 或持久化任何凭据
