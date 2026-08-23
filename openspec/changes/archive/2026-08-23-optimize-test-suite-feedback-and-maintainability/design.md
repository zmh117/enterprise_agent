## Context

当前 checkout 的测试基线为：后端 1407 个收集用例，1377 通过、30 跳过，耗时 442.84 秒；前端 117 个用例耗时 6.20 秒。后端测试有 168 个文件、约 6.1 万行，11 个超过 1000 行的文件占后端测试代码 27.7%。测试代码中出现 86 次 `build_test_container(...)`，33 个文件显式执行 migration；现有 Pytest 配置只有一个几乎未使用的 `integration` 标记，CI 将后端完整套件作为单一门禁。

平台属于身份、授权、发布快照、工具治理、文件处理和交付边界密集的系统。Canonical `platform-operations` 已要求真实端到端链路以及关键拒绝、恢复、迁移和 Secret 不泄漏证据，因此测试优化不能用删行、合并不同失败路径或以容器健康替代业务验收的方式完成。

## Goals / Non-Goals

**Goals:**

- 为每个后端测试文件提供唯一、可审计的测试层级，并让新文件缺少分类时失败关闭。
- 提供稳定的 PR 快速套件和完整回归入口，在参考环境中分别达到不超过 120 秒和 300 秒的目标。
- 在保持逐测试数据库隔离的前提下复用已经完成 migration 的 SQLite 基线。
- 降低跨领域 helper 和高变更大文件的维护成本，保持 scenario 与安全边界可读。
- 用完整套件、耗时报告和覆盖映射证明优化没有减少规范要求的行为覆盖。

**Non-Goals:**

- 不把测试总行数、文件数或用例数设为成功指标。
- 不修改生产 API、数据库 schema、领域行为、授权或运行时协议。
- 不用共享可变数据库、跨测试执行顺序或仅重试失败用例换取速度。
- 不在本变更中替代需要真实外部服务、Compose 或人工确认的验收证据。

## Decisions

### 1. 使用集中式测试层级清单，而不是一次性移动全部测试文件

新增后端测试层级清单，将每个 `test_*.py` 文件显式归入且只归入一个层级：

- `unit`：纯领域逻辑，不创建 Container、不运行 migration、不访问网络。
- `contract`：进程内 API、Repository、Runtime Adapter 或协议契约，可使用隔离的本地数据库和测试替身。
- `integration`：需要 PostgreSQL、外部 Runtime、凭据或其他显式启动的服务。
- `acceptance`：跨入口、Job、Worker、Tool、文件或 Delivery 的业务链路及其拒绝/恢复路径。
- `migration`：Migrator、活动 baseline、legacy manifest、checksum、PostgreSQL/SQLite schema 等价性和升级路径。

Pytest collection hook 根据清单添加 marker；文件未分类、重复分类或清单引用不存在文件时直接失败。集中清单比立即移动 168 个文件产生更小的导入和 Git 历史扰动，同时仍然让分类变更显式可审查。待领域目录稳定后可另行迁移物理目录。

备选方案是将未标记测试默认为 `contract`，但这会让新测试静默进入错误门禁，因此不采用。立即按层级移动所有文件也可实现分类，但会制造大规模 rename、增加当前多个 active change 的冲突风险，因此暂缓。

### 2. 快速门禁是完整回归的真子集，不替代完整回归

提供三个稳定入口：

- `test-fast`：执行 `unit` 与 `contract`，作为 PR 必跑门禁。
- `test-full`：执行全部非显式外部凭据测试，保持当前 `backend/tests` 完整语义。
- 各层级独立入口：用于 CI 分片、定位和按需验收。

主分支和发布流程继续执行 `test-full`；migration、acceptance、integration 不会因为快速门禁存在而被删除。CI 输出收集数、通过/跳过数、总耗时和最慢用例。参考预算是本 change 的验收目标，不使用不稳定的单次 wall-clock 硬超时制造随机失败；若预算未达到，任务不得标记完成，必须保留基线和差距说明。

### 3. 迁移基线按进程构建一次，逐测试复制，迁移语义测试显式绕过

在测试基础设施中构建只读 SQLite 模板：

1. 计算活动 migration 文件身份摘要。
2. 在进程或 Pytest worker 范围内对临时 SQLite 文件运行一次真实 `Migrator`。
3. 每次创建普通测试 Container 时复制模板到唯一临时数据库文件。
4. 在副本上加载配置、执行 seed 和测试写入；测试结束关闭连接并清理副本。
5. migration 层级以及明确传入非默认 migration 目录、`migrate=False` 或持久化 DSN 的测试不使用模板。

复制后的数据库绝不在测试间共享，避免事务外提交、线程、后台回调和连接池导致状态泄漏。模板摘要防止同一进程内 migration 内容变化后误用旧 schema。

备选方案是 session 级共享数据库配合事务回滚，但当前测试存在多连接、显式提交、并发和重启场景，无法可靠回滚，因此不采用。仅引入并行执行会放大重复 migration 和共享资源风险，也不作为第一步。

### 4. 以领域 scenario builder 替代跨领域“大 helper”

将现有通用 helper 按职责拆分为 Container/Database、Business Application、Authorization、Channel/Delivery 等测试支持模块。Builder 只负责 Arrange，并返回具名领域对象；断言继续留在测试中，避免 helper 隐藏安全边界或把多个拒绝路径压成一个参数化用例。

优先处理同时满足高体积和高变更的文件：业务应用控制面、任务文件合成验收、Python Runtime、角色授权、Schema Migration 和 Agent Profile 前端测试。拆分按 Requirement/不变量边界进行，不以机械的 500 或 1000 行阈值自动拆分。

### 5. 删除测试前必须提供覆盖等价证据

重复测试候选必须记录旧测试、替代测试、覆盖的 canonical Requirement、正常路径、拒绝路径、恢复路径和审计/Secret 边界。仅当这些维度等价且完整套件通过时才能删除；仅断言相似、使用相同 fixture 或降低行数均不是删除依据。

## Risks / Trade-offs

- [集中清单初次录入可能分类错误] → 先输出各层级清单和收集数，审查涉及外部服务、migration、跨组件链路的文件，并用缺失/重复分类测试失败关闭。
- [SQLite 模板掩盖 Migrator 回归] → migration 层级永远从指定初始状态运行真实 Migrator；模板构建本身也必须验证 migration ledger 与摘要。
- [文件数据库与 `:memory:` 在连接语义上存在差异] → 保留少量内存数据库契约测试，并对并发、重启、多连接和事务边界运行聚焦回归；发现语义差异时允许目标测试退出模板路径。
- [CI 运行时间受 runner 波动影响] → 保存命令、环境、收集数和 wall-clock 证据，用同一参考环境重复测量；预算作为 change 完成门槛而非单次硬超时。
- [拆分 helper 产生大范围冲突] → 按领域逐批迁移调用方，当前 active change 涉及的文件最后处理，每批保持完整套件可运行。
- [快速门禁造成开发者误以为已经完成验收] → 命令和 CI 名称明确区分 `fast` 与 `full`，发布说明必须同时报告完整回归和未执行的真实外部验收。

## Migration Plan

1. 提交测试层级清单、collection 校验和稳定命令，先保持 CI 仍执行完整套件。
2. 引入隔离 SQLite 模板并迁移一组高重复 migration 的契约测试，比较收集数、结果和耗时。
3. 扩大模板使用范围；遇到语义差异的测试显式保留原始路径。
4. 启用 PR 快速门禁，同时在独立 CI Job 保留完整回归。
5. 按领域拆分 helper 与热点测试文件，逐批运行聚焦和完整回归。
6. 达到预算并完成覆盖映射后再标记 change 完成；任何阶段均可回退到原始 `pytest backend/tests` 入口。

## Open Questions

无。用户已确认采用“不设硬性减行目标、PR 快速套件不超过 2 分钟、后端完整套件不超过 5 分钟并保留 canonical 验收覆盖”的方案。
