## ADDED Requirements

### Requirement: 自动化测试必须具有唯一且失败关闭的执行层级
仓库 SHALL 将每个自动化测试文件唯一分类为 `unit`、`contract`、`integration`、`acceptance` 或 `migration`；分类 SHALL 由版本控制下的机器可读事实驱动。新增测试缺少分类、同时命中多个分类或清单引用不存在文件时，测试收集 MUST 失败，而不是静默选择默认层级。

#### Scenario: 新测试缺少层级
- **WHEN** 开发者新增测试文件但没有将其加入唯一测试层级
- **THEN** 测试清单校验和 Pytest collection 失败并报告该文件

#### Scenario: 测试属于多个层级
- **WHEN** 同一个测试文件被配置为两个或更多层级
- **THEN** 测试清单校验失败并列出冲突层级

#### Scenario: 按层级执行测试
- **WHEN** 开发者或 CI 选择任一测试层级
- **THEN** 系统只收集该层级的测试并报告稳定的收集数、通过数、跳过数和耗时

### Requirement: 快速反馈不得替代完整回归
仓库 SHALL 提供稳定的 PR 快速测试入口和后端完整回归入口。快速入口 MUST 只选择已分类的 `unit` 与 `contract` 测试；完整入口 MUST 保持所有本地可执行测试的现有覆盖，并由主分支或发布门禁执行。存在快速入口不得成为删除 `integration`、`acceptance`、`migration`、拒绝路径或恢复路径测试的依据。

#### Scenario: Pull Request 快速门禁
- **WHEN** Pull Request 运行默认快速测试入口
- **THEN** CI 执行全部 `unit` 与 `contract` 测试并清晰声明尚未代表完整回归或真实外部验收

#### Scenario: 主分支完整回归
- **WHEN** 变更进入主分支或发布验证
- **THEN** CI 执行所有本地可执行层级并保留显式外部集成测试的跳过原因

#### Scenario: 快速测试通过但验收测试失败
- **WHEN** 快速入口通过而 `acceptance`、`migration` 或其他完整回归层级失败
- **THEN** 系统不得把该变更报告为完整质量验收通过

### Requirement: 测试数据库加速必须保持逐测试隔离和迁移真实性
非 migration 语义的 SQLite 测试 MAY 复用一次构建的已迁移只读模板，但每个测试 MUST 使用唯一数据库副本并独立执行 seed 与写入。验证 Migrator、schema baseline、checksum、legacy ledger、升级路径或指定初始数据库状态的测试 MUST 绕过模板并执行真实迁移流程。测试不得依赖执行顺序或其他测试留下的状态。

#### Scenario: 普通契约测试创建数据库
- **WHEN** 非 migration 契约测试请求已迁移测试数据库
- **THEN** 测试基础设施从与当前 migration 身份一致的模板创建唯一副本，且对副本的写入不会被其他测试观察到

#### Scenario: Migration 测试验证空库升级
- **WHEN** migration 层级测试验证空 SQLite 或 PostgreSQL 数据库的 baseline 与后续迁移
- **THEN** 测试不使用已迁移模板，而是从声明的初始状态执行真实 Migrator 并验证 ledger 和 schema

#### Scenario: Migration 内容发生变化
- **WHEN** 同一测试进程使用的活动 migration 身份与模板身份不一致
- **THEN** 测试基础设施拒绝复用旧模板并重新构建或失败关闭

### Requirement: 测试反馈预算必须可测量且不得通过缩减覆盖达成
仓库 SHALL 提供可复现的测试基线命令并输出执行环境、收集数、通过/跳过数、总耗时和最慢测试。该变更在约定参考环境中的验收目标为 PR 快速套件不超过 120 秒、后端完整套件不超过 300 秒。预算只能通过测试分层、隔离基础设施复用、无语义损失的 fixture 重构或经过隔离验证的并行执行达成，不得通过删除规范覆盖、隐藏失败、依赖重试或改变测试选择口径达成。

#### Scenario: 记录优化前后基线
- **WHEN** 维护者评估测试优化效果
- **THEN** 使用相同参考命令和环境记录优化前后收集数、结果、耗时和最慢测试，并说明所有选择条件

#### Scenario: 耗时达到目标但收集数下降
- **WHEN** 快速或完整套件耗时达到预算，但本应包含的测试收集数或层级覆盖下降
- **THEN** 该优化不得通过验收，直到覆盖差异被解释并证明符合规范

#### Scenario: 参考环境未达到预算
- **WHEN** 实现完成后快速套件超过 120 秒或后端完整套件超过 300 秒
- **THEN** 对应性能任务保持未完成并记录差距，不得仅以测试全部通过宣称本变更完成

### Requirement: 删除重复测试必须具有规范覆盖等价证据
删除或合并自动化测试前，维护者 MUST 记录原测试、替代测试、对应 canonical Requirement，以及正常、拒绝、恢复、审计和 Secret 边界的覆盖等价关系。仅代码相似、使用相同 fixture、文件过长或希望减少行数均不得作为删除依据。

#### Scenario: 两个测试断言相似但失败边界不同
- **WHEN** 两个测试具有相似正常路径断言但覆盖不同授权、恢复或审计边界
- **THEN** 系统保留独立测试或提供同时覆盖两个边界的明确替代测试

#### Scenario: 重复测试具有完整替代证据
- **WHEN** 维护者证明替代测试覆盖同一 Requirement 及全部相关边界，并且完整回归通过
- **THEN** 可以删除重复测试并在变更证据中记录映射
