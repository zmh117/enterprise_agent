## 1. 基线与测试层级

- [x] 1.1 在 change evidence 中记录参考环境、测试行数、后端/前端收集结果、完整耗时和最慢测试基线
- [x] 1.2 新增机器可读的后端测试层级清单，将每个 `test_*.py` 文件唯一归入 unit、contract、integration、acceptance 或 migration
- [x] 1.3 注册五类 Pytest marker，并实现 collection hook 对缺失、重复和失效清单项失败关闭
- [x] 1.4 为层级清单校验、marker 注入、按层级选择和新增未分类文件补充聚焦测试
- [x] 1.5 在 Makefile 提供 `test-fast`、`test-full` 和各层级稳定入口，并输出收集结果、总耗时和最慢测试

## 2. 隔离 SQLite 迁移模板

- [x] 2.1 为测试专用 Container 构建实现活动 migration 身份摘要和进程内只读 SQLite 模板缓存
- [x] 2.2 让普通内存 SQLite 测试从模板恢复到唯一共享内存数据库，保留 `migrate=False`、非 SQLite 和显式 migration 验证的原始路径
- [x] 2.3 补充模板副本隔离、并发连接可见性、migration 身份变化、seed 独立性和旧路径绕过测试
- [x] 2.4 将重复执行完整 migration 的 topology fixture 迁移到隔离模板，并验证参数化用例不共享状态
- [x] 2.5 运行高频 Container 测试文件并记录迁移模板前后的结果与耗时

## 3. CI 分层与覆盖保护

- [x] 3.1 将 Pull Request 快速门禁配置为完整 unit 与 contract 层级，并明确声明它不是完整验收
- [x] 3.2 保留独立后端完整回归门禁，确保主分支和发布路径执行所有本地可执行层级
- [x] 3.3 新增层级收集数快照与 Requirement 覆盖映射，记录 migration、拒绝/恢复、审计、Secret 和真实业务验收归属
- [x] 3.4 增加防回归测试，证明快速入口是完整入口真子集且完整入口没有减少当前收集范围

## 4. 测试支持代码与热点重构

- [x] 4.1 将 `backend/tests/helpers.py` 按 Container/Database、Business Application、Authorization、Channel/Delivery 职责拆分，并保留阶段性兼容导出
- [x] 4.2 将业务应用控制面和角色授权热点测试迁移到具名 scenario builder，保持断言留在测试函数内
- [x] 4.3 将任务文件合成验收和 Python Runtime 热点测试迁移到领域 builder，不合并不同拒绝或恢复路径
- [x] 4.4 提取前端共享 response/render 测试工具并迁移 Agent Profile 热点测试
- [x] 4.5 记录重复测试审查结果；仅在具备 canonical Requirement 与失败边界等价证据时删除重复测试

## 5. 验证与性能验收

- [x] 5.1 运行层级清单、SQLite 模板、热点重构的聚焦测试及 Ruff、mypy、前端 lint/typecheck
- [x] 5.2 在同一参考环境运行 PR 快速套件，确认完整 unit 与 contract 收集且耗时不超过 120 秒
- [x] 5.3 在同一参考环境运行后端完整套件，确认收集范围不下降、全部本地用例通过且耗时不超过 300 秒
- [x] 5.4 运行前端完整测试、OpenSpec strict validation、Markdown link、`git diff --check` 和必要的 Compose 配置检查
- [x] 5.5 将优化后收集数、通过/跳过数、耗时、最慢测试和未执行真实外部验收写入 evidence
