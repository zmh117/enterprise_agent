## 1. 退役基线与只读门禁

- [x] 1.1 为 TypeScript Runtime 退役增加只读 preflight，按环境汇总 Definition、Publication、Application revision/deployment、各状态 Job、retry/outbox/queue 和 Runtime 配置，只输出标识、计数与脱敏状态
- [x] 1.2 为 preflight 增加数据库不可达、队列不可达、活动 TypeScript Deployment、非终态 TypeScript Job 和残留 Runtime 配置的失败关闭测试
- [x] 1.3 在退役报告中明确区分当前 checkout、当前目标环境和未验证环境，不允许用本地零计数替代其它环境证据
- [x] 1.4 记录实现前 schema head、Runtime protocol、默认 Runtime、当前 TypeScript 引用与 Job 状态基线，不读取或输出 Secret、Prompt、业务消息或文件正文

## 2. Runtime合同事实源迁移

- [x] 2.1 将 `agent-runtime/contracts/` 的 schema、limits、errors 与 golden fixtures 等内容迁移到仓库级 `contracts/agent-runtime/`
- [x] 2.2 更新 Python validators、协议代码、Dockerfile COPY、测试和检查脚本，使其只从新的合同目录读取
- [x] 2.3 增加合同目录完整性测试，验证受支持协议版本、fixture、request digest、稳定错误码和历史事件读取不因 TypeScript 代码删除而变化
- [x] 2.4 在删除旧目录前运行新旧合同文件内容/hash 对账并证明 Python Runtime 全部合同测试从新路径通过

## 3. Python Runtime能力收口

- [x] 3.1 用现有 accepted、tool、completed、failed、cancel、timeout、digest conflict 和终态恢复 fixtures 覆盖 Python Runtime 的全部受支持协议版本
- [x] 3.2 验证 Python Runtime 的模型绑定、active Secret 解析、隔离 env、SDK/CLI 依赖、max turns、timeout、max tool calls 和稳定错误分类；仅在合同缺口要求时受控升级 SDK/CLI
- [x] 3.3 验证 Python Runtime 对 `tool-mcp` 与 ONES MCP 的精确 Tool/schema/scope、任意 URL 拒绝、危险工具拒绝、运行事件与统一 MCP 审计
- [x] 3.4 验证 Python Runtime 的 File MCP bridge、Principal JWT、自动物化、流式上传、TXT/LOG/Markdown 格式策略、沙盒路径/符号链接/容量守卫和终态清理
- [x] 3.5 把保存后模型连接 probe 和配置向导草稿 probe 统一委托给 `python-agent-runtime`，保留 RBAC、限流、SSRF、revision/hash、无 Tool、单轮、短超时和脱敏响应
- [x] 3.6 增加 Python 模型 probe 成功、Credential/host/revision 漂移、超时、Provider 错误脱敏和不产生 MCP 调用的回归测试

## 4. 冻结TypeScript控制面新写入

- [x] 4.1 将 Agent 创建、seed/bootstrap、草稿校验、发布和回滚入口收敛为新事实只接受 `python-v1`，同时保留历史 `typescript-v1` Definition/Publication 只读查询
- [x] 4.2 阻止历史 TypeScript Publication 创建草稿、成为当前回滚目标或产生新 Job，并对旧客户端返回稳定迁移错误而非静默改写
- [x] 4.3 将 Business Application 发布校验收敛为只接受 Python Agent Publication，并禁止历史 TypeScript Application Publication 重新激活
- [x] 4.4 保持新 Application revision 显式引用 Python Publication、重新计算 hash、重新校验 MCP/文件/策略并使用 `expected_revision` 激活，禁止原地修改旧快照
- [x] 4.5 更新 Agent Profile 与 Business Application 前端，移除 Runtime 选择和 TypeScript 可编辑动作，同时以“已退役、只读”展示历史 runtime kind、revision 与 hash
- [x] 4.6 增加后端 API、repository/service 和前端测试，覆盖 Python 正常路径、TypeScript 新写入拒绝、历史只读展示和不可重新激活

## 5. TypeScript引用显式迁移与排空

- [x] 5.1 提供只接受精确 Agent/Application Publication ID、目标 Python Publication ID 与 expected revision 的受控迁移命令，默认 dry-run 且不得猜测配置或复制 Secret
- [x] 5.2 让迁移命令创建新的 Application revision/publication 并显式 activate，记录不含敏感值的旧新引用、actor、correlation 和结果审计
- [x] 5.3 为缺少确定性 Python 替代、hash/Tool/策略不一致、并发 revision 冲突和部分失败增加原子回滚/阻塞报告测试
- [x] 5.4 在每个目标环境运行冻结版本与只读 preflight，迁移所有活动 TypeScript Deployment，并保存脱敏前后对账证据
- [x] 5.5 等待、取消或按原 TypeScript Runtime 确定性终结全部非终态 TypeScript Job，确认 retry/outbox/queue 无对应可执行消息且不改写 runtime kind
- [x] 5.6 只有在全部目标环境通过活动引用为零、非终态 Job 为零和队列为零门禁后，才批准进入 TypeScript 运行面删除阶段

## 6. 生产装配收敛为单一Python Runtime

- [x] 6.1 将生产 Runtime client registry、Job 创建、Worker 和 stub 测试装配收敛为 `python-v1`，对未知或退役 runtime kind 失败关闭
- [x] 6.2 更新 API/runtime readiness，使其只报告 Python Runtime 的协议、SDK/CLI 和脱敏依赖状态，并拒绝残留 TypeScript URL、allowed host 或 client 注册
- [x] 6.3 更新 Compose、环境示例、Secret usage、网络和所有 API/Worker/Channel worker 依赖，删除 `typescript-agent-runtime` 服务及健康耦合
- [x] 6.4 更新 backend Dockerfile 和镜像合同，确保 Worker 不含 Agent SDK/CLI、Python SDK/CLI 只存在于 Python Runtime 镜像且不再构建 TypeScript Agent Runtime 镜像
- [x] 6.5 删除 TypeScript 模型 probe 默认值、环境/Application allowlist、双 Runtime feature flag 和运行配置字段；旧配置存在时由预检明确报告
- [x] 6.6 更新 RabbitMQ Worker 对退役 TypeScript 消息的幂等终态处理与失败关闭测试，禁止跨 Runtime fallback 或重复模型调用

## 7. 删除TypeScript Runtime实现和重复表面

- [x] 7.1 删除 Python 到 TypeScript Runtime 的生产 client、双 Runtime registry/readiness/acceptance 代码及只服务于 TypeScript 的后端测试
- [x] 7.2 在合同迁移和排空门禁完成后删除 `agent-runtime/` 中的 TypeScript Runtime 源码、生成器、测试、Dockerfile、package/lockfile 和 Runtime 专用脚本
- [x] 7.3 删除 `docker-compose.dual-runtime-acceptance.yml` 及双 Runtime fault proxy/fixture，使用 Python 单 Runtime acceptance 替换仍有价值的 retry、cancel 和终态恢复用例
- [x] 7.4 清理前端、文档、运维命令、架构图和测试中把 TypeScript Runtime 描述为受支持执行路径的引用，同时保留历史事实展示说明
- [x] 7.5 扫描 `typescript-agent-runtime`、`typescript-v1`、`TYPESCRIPT_AGENT_RUNTIME_*` 和 `agent-runtime/` 残留，逐项分类为必须删除的运行依赖或必须保留的历史/迁移语义

## 8. 数据、Schema与回滚保护

- [x] 8.1 保持数据库 `runtime_kind`/`agent_runtime_kind` 和历史 `typescript-v1` 值可读，不添加把历史记录更新为 Python 的 backfill
- [x] 8.2 更新空库 seed 和 schema fact source，使新环境只创建 Python Agent，同时证明旧数据库中的 TypeScript Definition、Publication、终态 Job 和审计仍可查询
- [x] 8.3 为历史 TypeScript 事实增加只读 API/序列化回归，确保 UI 和审计显示原 runtime kind 且不会触发执行、回滚或重新激活
- [x] 8.4 编写分阶段部署与回滚步骤：删除前可恢复 TypeScript 服务排空；删除后若回滚，必须同时恢复旧代码/镜像/配置后才允许激活旧 Publication
- [x] 8.5 明确记录本变更不收窄数据库 CHECK/枚举；任何未来删除历史 runtime kind 的 contract migration 必须另建 change、经过保留期、备份和全环境证据

## 9. 验证与完成证据

- [x] 9.1 运行 Runtime 合同、Python Runtime、模型连接、Agent/Application 发布、Worker/retry、MCP、文件工作区、历史投影和退役 preflight 的 focused backend tests
- [x] 9.2 运行完整 backend test suite、静态检查和 schema/migration tests，并记录通过、跳过与任何环境限制
- [x] 9.3 运行 frontend tests、typecheck 和 production build，验证无 Runtime 选择且历史 TypeScript 标签仍安全显示
- [x] 9.4 构建 Python Runtime、Worker、API 与默认 Compose 镜像，验证服务清单、Secret mount、网络、readiness 和镜像依赖合同中不存在 TypeScript Runtime
- [x] 9.5 使用合成数据证明 Channel/API→Outbox→RabbitMQ→Worker→Python Runtime→Tool MCP/ONES MCP/File Service→Job终态→Delivery 的新鲜成功闭环
- [x] 9.6 使用合成数据证明 retry delay/dead-letter、不可重试失败、取消、digest 恢复、Principal/Tool/路径拒绝、文件冲突、沙盒清理和 Secret 不泄漏
- [x] 9.7 运行 `openspec validate retire-typescript-agent-runtime --strict`、Markdown/链接检查、`git diff --check` 和最终残留扫描
- [x] 9.8 仅在所有目标环境 preflight、控制面切流、TypeScript Job 排空和新鲜 Python E2E 证据齐全后，才把变更标记为可归档
