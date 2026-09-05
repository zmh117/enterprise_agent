## 1. 冻结现有准入行为

- [x] 1.1 在 `CreateAgentJobService.execute()` 层增加特征测试，覆盖“生成 md 文件记录我今天的对话”与“根据今天上传的文件生成汇总.md”，同时断言 Job/系统通知、reason code、文件依赖、Workspace 和 Manifest 结果。
- [x] 1.2 增加当前附件、显式 File/Version 引用、引用消息、完整文件名、指示语、非法日期、空时间窗口、候选超限与绑定歧义的完整链路行为矩阵，冻结 canonical 优先级和中文通知。
- [x] 1.3 增加 Workspace 已启用/禁用、已有/不存在时的生命周期特征测试，记录系统通知路径与变更前一致的 Workspace 副作用。
- [x] 1.4 增加部署前 `file_turn_dependencies` payload fixture 及等待中附件完成恢复测试，证明旧 Job 无需 migration 即可恢复且不会纳入新增候选。

## 2. 建立 deep 文件准入 module

- [x] 2.1 在 Job application 层建立单一文件准入 module 和不可变 Admission Plan，承载有效输出意图、Gate、安全通知事实、冻结依赖、Workspace requirement、Manifest binding plan 与兼容恢复 payload。
- [x] 2.2 将现有输出文件意图识别、文件来源优先级、时间窗口解析、候选选择、能力推导、Gate 和安全通知 helper 收敛为该 module 的内部 implementation，保持词表、顺序、原因码与中文文案不变。
- [x] 2.3 在 Admission Plan 内完成 Workspace requirement、Working Set 与自动物化计划，确保 `TIME_WINDOW` 始终只产生最多 20 个 `METADATA` 候选且不自动物化正文。
- [x] 2.4 实现从现有 `file_turn_dependencies` 安全 payload 恢复冻结依赖并仅刷新来源/可读性状态的 Gate 重新评估路径。

## 3. 迁移调用路径并删除 seam 泄漏

- [x] 3.1 调整活动 Workspace 与候选读取路径，使 `CreateAgentJobService` 在同一 Unit of Work 内先获取只读事实、形成一次 Admission Plan，再应用文件相关副作用。
- [x] 3.2 迁移 Agent Job 创建和系统通知路径，保留 ingress 输出意图 hint，但删除向 resolver/Workspace 分别传递的有效意图预判与 `_file_turn_gate` glue。
- [x] 3.3 迁移 Workspace、File MCP Tool Snapshot 和 Job File Manifest 调用，使其直接消费 plan 的已决事实，并删除调用方针对 `TIME_WINDOW`、能力类型、候选数量和自动物化的条件分支。
- [x] 3.4 迁移附件处理完成路径，通过同一准入 module 恢复和重新评估 Gate；验证当前附件 `current:<ordinal>` 映射与旧 payload 兼容。
- [x] 3.5 删除 `manifest_service.py` 中旧输出意图 helper、旧 `file_context.py` public seam 及无引用兼容代码，确认 File Service 未反向依赖 Job application 类型。

## 4. 回归与交付验证

- [x] 4.1 运行文件准入、Agent Job 创建、附件恢复、Task Workspace 与 Job File Manifest 定向测试，并确认新增完整链路行为矩阵全部通过。
- [x] 4.2 运行 Ruff、受影响 Python 模块的 Mypy、完整 backend 测试和 `git diff --check`；若存在已知基线失败，单独记录且不得归因于本 change。
- [x] 4.3 运行 `docker compose config --quiet` 与 `openspec validate deepen-agent-job-file-admission --strict`，确认无 migration、依赖或 Compose 配置漂移。
- [x] 4.4 通过本机实际 Agent Job 创建入口复验两个关键请求，分别记录 `enqueue_job + no_file_dependency + 0 dependencies` 与 `METADATA + TIME_WINDOW + no auto-materialization` 证据，并明确该本地证据不代表真实 DingTalk、File MCP 或生产环境验收。
