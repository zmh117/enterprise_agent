## 1. 实施前事实核对与合同冻结

- [x] 1.1 检查当前工作树、migration head、Schema fact-source ledger、Runtime protocol ledger 和 `unify-mcp-operation-audit` 实际落地状态，记录本 change 可使用的下一个 migration 版本与 Runtime minor version，不覆盖未提交或已应用变更
- [x] 1.2 为 TypeScript/Python Runtime 准备相同的 SDK fixture，覆盖 init、assistant/model response、API retry、成功 ResultMessage、错误 ResultMessage、缺失 usage 和 MCP 连接失败，fixture 不含真实 Prompt、回复或认证材料
- [x] 1.3 先增加失败的共享 Runtime 合同测试，固定 `runtime_initialized`、`model_call`、`api_retry` 和扩展 terminal 的必填/可空字段、数值上限、未知 major 拒绝及旧 minor 兼容行为
- [x] 1.4 更新共享协议 schema、错误分类 ledger、golden fixtures 和 TypeScript/Python 生成类型，并验证生成产物与源 schema 无漂移

## 2. Runtime SDK 消息归一化

- [x] 2.1 在 TypeScript Runtime 中实现 SDK init、模型轮次、API retry 和 ResultMessage 的白名单归一化，保留安全模型/MCP 状态、四类 Token、query 耗时、按模型 usage 与估算成本
- [x] 2.2 在 TypeScript Runtime 中实现基于本地单调时钟的 `SDK_OBSERVED` 轮次耗时；没有可靠请求起点时输出 `UNAVAILABLE` 和空耗时，不用工具或 Job 总耗时推算
- [x] 2.3 在 Python Runtime 中实现与 TypeScript 相同的事件字段、缺失值、错误码、模型轮次身份和终态语义，并通过双 Runtime golden fixture 对比
- [x] 2.4 扩展两套 Runtime 的终态恢复账本，确保相同 `invocation_id + request_digest` 只能接受一个一致终态，恢复时不改变 sequence 或重复发出模型轮次
- [x] 2.5 增加 Runtime 负向测试，证明 Prompt、完整回答、raw SDK message、private thinking、Provider/MCP 原始载荷和 Secret 不进入事件或 stderr

## 3. PostgreSQL 执行审计事实

- [x] 3.1 使用实施时确认的下一个 expand migration 创建 `agent_job_execution_summary`，加入 1:1 外键、核算状态、计数、四类 Token、耗时、固定 schema 模型 usage、定点估算成本、失败阶段、retry 结果、时间戳和非负/长度约束
- [x] 3.2 在同一 expand migration 创建 `agent_model_call`，加入 Job/invocation/sequence 稳定身份、模型与安全 Provider 标识、状态、时间、耗时来源、可空 Token、停止原因、错误字段、幂等唯一约束和分页/筛选索引
- [x] 3.3 配置两表随 `agent_job` 既有保留策略清理，加入表列注释，并通过外键与清理测试证明不会形成无主投影
- [x] 3.4 将两张新表登记到 `backend/app/shared/schema_fact_sources.json`，更新 SQLite 测试 schema 和 PostgreSQL migration/fact-source 一致性测试，确认未向 `agent_job` 添加统计列
- [x] 3.5 为执行汇总和模型轮次增加领域值对象、枚举与 repository upsert/list 接口，统一验证未知值为 `NULL`、64 位非负计数和有界字符串

## 4. Worker 幂等聚合与失败定位

- [x] 4.1 扩展 Runtime client 和 `AgentRunResult`，双读旧 minor 与新 minor，并把合同有效的初始化、模型轮次、retry 和 ResultMessage 交给持久化层
- [x] 4.2 在 Worker 事务中幂等保存 `agent_runtime_event` 与 `agent_model_call`，以 Job、invocation 和 sequence 拒绝冲突重放，同时保持旧协议 Job 可执行
- [x] 4.3 实现从单 Job 全部唯一 invocation terminal 重算 `agent_job_execution_summary`，禁止增量盲加，并正确汇总多次 Job retry 已实际产生的 Token、耗时和估算成本
- [x] 4.4 实现 `COMPLETE | PARTIAL | UNAVAILABLE` 核算规则：优先 `modelUsage`，只有主循环 `usage` 时为部分，字段缺失时保持未知且不伪造零值
- [x] 4.5 实现基于 typed SDK/内部错误与工具/MCP 状态的失败分类器，覆盖 `RUNTIME_START`、`RUNTIME_PROTOCOL`、`MCP_CONNECTION`、`MODEL_API`、`TOOL_PERMISSION`、`TOOL_EXECUTION` 和 `UNKNOWN`，禁止解析自由错误文本猜测
- [x] 4.6 将 Job retry 是否耗尽作为独立字段更新，确保其不覆盖模型、Runtime 或工具根因，并为异常退出无 terminal 的 Job 保存部分核算状态
- [x] 4.7 提供受控的按 Job 汇总重建命令或服务方法，从合同事件幂等重建两张投影，并验证重建不改变 `agent_job` 生命周期事实

## 5. 管理端授权查询与投影

- [x] 5.1 扩展运行记录列表 repository 和 DTO，联接 1:1 汇总并支持时间、用户安全标识、Agent、执行状态、Delivery 状态、失败阶段和模型筛选，缺失汇总返回 `UNAVAILABLE`
- [x] 5.2 扩展现有 Job evidence/detail API，返回执行汇总、分页模型轮次、既有 `agent_tool_call`/`mcp_operation_audit` 关联和 Delivery 证据，不暴露通用 Runtime event JSON
- [x] 5.3 在查询层保持执行与投递状态独立，并从 `delivery_attempt` 推导只用于展示的 `DELIVERY` 失败位置，不反写执行汇总
- [x] 5.4 复用现有登录、业务应用运维权限和平台管理员授权，对列表与详情执行服务端租户/应用范围过滤，禁止客户端筛选参数扩大可见范围
- [x] 5.5 增加 API 合同、分页、排序、旧 Job、未知统计、执行成功但投递失败以及不存在/越权 Job 不泄漏记录存在性的测试

## 6. 运行中心页面

- [x] 6.1 扩展 `frontend/src/contexts/operations/domain/runtime-record.ts` 的 Zod schema 和查询模型，区分未知值、估算成本、核算状态、执行状态与 Delivery 状态
- [x] 6.2 扩展运行记录列表筛选和列展示，包含用户、Agent、总耗时、API 总耗时、四类 Token、估算成本、模型、工具摘要和稳定失败位置，并为部分/不可用统计提供明确状态
- [x] 6.3 扩展 Job 详情，使用分页模型轮次表展示模型、安全 request/message 标识、状态、Token、停止原因和耗时来源；逐轮耗时固定标注“SDK 观测”，不可用时不显示伪造数值
- [x] 6.4 在详情中并列展示 Agent 执行与 Delivery 状态，并链接既有工具/MCP 安全证据；Agent 成功但投递失败时只把失败位置显示为 Delivery
- [x] 6.5 增加运行中心组件测试，覆盖完整、部分、不可用、模型轮次分页、无逐轮耗时、API retry、工具拒绝、执行失败和 Delivery 失败视图

## 7. 幂等、安全与集成回归

- [x] 7.1 增加 Worker/repository 测试，覆盖相同终态重放、相同模型轮次重放、重复 MQ 消费、多 invocation retry、崩溃恢复和汇总重建，断言 Token 与成本从不重复累计
- [x] 7.2 增加双 Runtime 组合验收，覆盖成功、API retry、MCP 连接失败、模型 API 失败、工具权限拒绝、工具执行失败、超时和最大轮次/工具次数耗尽
- [x] 7.3 增加 Secret 泄漏门禁，对新表、Runtime event、API JSON、页面 fixture 和日志扫描认证材料、原始业务正文与 private thinking，确认仅有稳定分类和有界脱敏摘要
- [x] 7.4 增加 PostgreSQL 集成测试，验证 migration、约束、索引、定点成本精度、64 位 Token、级联清理和 Schema fact-source parity；SQLite 仅作为快速回归而不替代 PostgreSQL 证据
- [x] 7.5 运行后端、agent-runtime 和 frontend 受影响测试集及 `git diff --check`，确认未引入 OpenTelemetry 依赖、Collector/Tempo/audit-ingestor 服务或新的未治理事件查询接口

## 8. 受控发布与证据

- [ ] 8.1 在测试环境先应用 expand migration，再部署双读 Worker，验证旧 Runtime Job 继续成功且新增统计为部分或不可用
- [ ] 8.2 发布两套新版 Runtime 并仅切换测试 Application/Agent Publication，完成真实 PostgreSQL、RabbitMQ、Job、Worker 与 Delivery 全链路验收，而不是仅依据容器健康状态
- [ ] 8.3 验证运行中心可按用户和 Agent 找到相同 Job，并能追溯总量、模型轮次、工具/MCP 证据、失败位置与 Delivery 状态；保存不含敏感内容的验收证据
- [ ] 8.4 验证停止 Publication 切换、恢复旧 Runtime 和隐藏页面功能的回滚流程，确认数据库 expand 事实与已产生审计记录仍可安全读取
- [x] 8.5 运行 `openspec validate improve-agent-run-audit --strict`，更新任务勾选与实现证据，并在申请 sync/archive 前明确区分规范、当前实现和真实环境验收状态

## 实施事实记录

- 2026-08-12：当前 migration head 为 `105_expand_unified_mcp_operation_audit.sql`，Runtime 已支持 v1.0/v1.1，`unify-mcp-operation-audit` 为 40/40；本 change 使用 migration `106` 和 Runtime protocol `1.2`。核对时工作树仅包含本 change 的未跟踪规划目录，未覆盖既有实现。
- 2026-08-12：当前代码已完成 Runtime v1.2 白名单投影、migration `106`、Worker 幂等汇总、安全查询 API 和运行中心页面；未向 `agent_job` 添加统计列，也未引入 OpenTelemetry、Collector、Tempo 或 audit-ingestor。
- 2026-08-12：本地验证包括 agent-runtime 41/41、frontend 101/101、backend 807 通过（29 跳过、2 subtests 通过）和独立 PostgreSQL 18 migration/约束集成 17/17；临时 PostgreSQL 容器已移除，现有 Compose 数据库未迁移、未修改。
- 2026-08-12：任务 8.1–8.4 仍未执行；当前实现状态不能替代测试环境 expand migration、RabbitMQ/Worker/Delivery 全链路、页面现场验收和回滚演练证据。
- 2026-08-13：修复 Python Runtime 镜像遗漏 v1.2 生成合同的发布阻断；生产镜像现在自动复制全部 `generated_runtime_contracts*.py` 并在构建时导入 `runtime_protocol`，TypeScript 镜像也在构建时导入合同与协议模块。同步为 TypeScript/Python Runtime 建立各自单一来源的受支持协议账本，增加逐版本 schema/limits 预检，修正 v1.2 limits 版本标识，并在 CI 中增加 Runtime 源码门禁与双生产镜像构建。
- 2026-08-13：两套生产镜像已在无网络、只读文件系统下完成导入/静态预检，并仅重建双 Runtime 容器；Python/TypeScript `/ready` 均为 200，Compose 依赖服务恢复运行。尚未执行测试 Publication 的真实 Job、页面追溯和回滚演练，因此任务 8.1–8.4 继续保持未勾选。
