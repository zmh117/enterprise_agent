## Context

当前 canonical baseline 把 `python-v1` 与 `typescript-v1` 定义为长期并存的两个独立 Agent Runtime，并把 Runtime kind 冻结到 Agent Definition、Agent Publication、Business Application Publication 和 Agent Job。默认 Compose 同时启动两个 Runtime，Worker/API 的 readiness 也依赖两者。

当前 checkout 中两套 Runtime 已分别实现模型调用、Runtime Grant、版本化执行协议、终态恢复、模型探测、MCP、文件传输、Job Sandbox、审计与错误分类。这些边界具有安全价值，但双语言实现本身没有形成独立业务能力。2026-08-17 核对的本地运行快照显示：两个 Runtime 均 ready，默认 Runtime 为 Python；64 个历史 Job 全部为 `python-v1`，同时仍存在一个 active TypeScript Agent Publication。该快照只证明当前本地环境，实施前必须在每个目标环境重新预检。

约束如下：

- Worker 必须继续只负责编排与业务状态，Claude Agent SDK 仍只能存在于独立 Runtime。
- Agent/Application Publication、Job 快照和运行审计是不可变事实，不得把历史 `typescript-v1` 静默改写为 `python-v1`。
- MCP Server 地址、Tool allowlist、Principal/Runtime Grant、Secret 解析与文件沙盒边界不得因单 Runtime 化而放宽。
- 当前协议 schema 和 golden fixtures 位于 `agent-runtime/contracts/`；删除 TypeScript 目录前必须先迁移该语言无关事实源。
- active change 和 archive 不是 canonical baseline，本变更不得借退役 Runtime 改写无关领域。

## Goals / Non-Goals

**Goals:**

- 所有新 Agent、Publication、Application 激活和 Job 统一使用 `python-v1`。
- 保留独立 `python-agent-runtime`、版本化协议、幂等终态、取消、模型探测、MCP 与文件沙盒能力。
- 安全迁移仍引用 TypeScript Publication 的控制面配置，并在删除服务前证明不存在未终态 TypeScript Job。
- 删除 TypeScript Runtime 的代码、镜像、客户端、配置、UI 入口和双实现验收负担。
- 保留历史 TypeScript Definition、Publication、Job 和审计的只读可解释性。

**Non-Goals:**

- 不把 Claude Agent SDK、CLI、模型 Secret 或 MCP 执行能力合并回 `agent-worker`。
- 不删除 `runtime_kind`、历史 `typescript-v1` 枚举值或任何终态 Job/Publication。
- 不改变 Tool MCP、ONES MCP、File MCP、Principal JWT、Runtime Grant、RBAC 或资源范围治理模型。
- 不引入任意 Runtime URL、Provider adapter、通用执行器或跨 Runtime fallback。
- 不以本变更顺带更换模型 Provider；Python SDK/CLI 只在通过现有合同所必需时受控升级。

## Decisions

### 1. 生产执行只保留独立 Python Runtime

`agent-worker` 继续通过语言无关的 Runtime client 契约调用独立 `python-agent-runtime`。生产 Registry 只注册平台固定的 Python client；单元测试仍可显式注入 stub。Runtime 只执行一次 attempt，不消费 RabbitMQ，也不写 Job、retry、Outbox 或 Delivery 业务状态。

选择 Python 而不是 TypeScript，是因为当前后端、Worker、领域模型、迁移、MCP 服务和运行数据均以 Python 为主，且现有 Job 全部走 Python。保留 TypeScript 会继续要求跨语言复制安全修复和协议演进。备选方案“保留 TS、删除 Python”会扩大控制面与运行面的语言边界并迁移现有默认路径；“长期双 Runtime”不能达到降低维护成本的目标。

### 2. 新写入收敛，历史事实不收窄

API、seed、Agent Profile 和 Business Application 发布校验只允许为新事实写入 `python-v1`。历史查询 schema 继续识别 `typescript-v1`，以便展示旧 Definition、Publication、Job、Runtime provenance 和审计；但历史 TypeScript Agent 不得再创建草稿、发布、回滚为当前版本或被应用重新激活。

数据库 CHECK/枚举在本变更中继续允许历史 `typescript-v1`。先由应用层停止新写入并完成运行态检查，避免同一发布同时执行 expand、数据迁移和不可回滚 contract/drop。未来若保留期和所有环境证据允许收窄数据库结构，必须另建 contract change。

### 3. 显式替换引用，不修改不可变快照

对仍引用 TypeScript Agent Publication 的活动 Business Application：

1. 选择或创建满足同一业务配置的 Python Agent 草稿并发布新的 Python Agent Publication；
2. 创建新的 Business Application revision，显式引用该 Python Publication；
3. 重新校验 MCP Tool、文件工作区、策略与 hash 后发布；
4. 使用 `expected_revision` 激活新 Application Publication；
5. 将旧 TypeScript Publication 保持为 inactive/read-only 历史。

不得修改旧 Agent/Application snapshot 的 runtime kind、hash 或引用。找不到确定性 Python 替代配置时必须停止迁移并生成阻塞报告，不得猜测或自动复制不兼容配置。

### 4. 采用“冻结、排空、切流、删除”四阶段退役

第一阶段部署兼容代码：禁止新建、发布和激活 TypeScript 配置，但暂时保留 TypeScript Runtime，以便既有非终态 Job 按原快照完成、取消或进入确定终态。第二阶段迁移所有活动 Application Deployment。第三阶段确认所有环境中 TypeScript Job 的 `PENDING`、`RUNNING`、`RETRY_WAIT` 等非终态计数为零，且队列没有对应可执行消息。第四阶段才删除 TypeScript service、client、Node 依赖和健康依赖。

运行时暂时不可用不能触发跨实现 fallback；若排空期 TypeScript Runtime 故障，应恢复该服务或将 Job 按既有策略终态化，而不是改写其 runtime kind。

### 5. 将版本化 Runtime 合同迁出 TypeScript 目录

把 `agent-runtime/contracts/` 中的 schema、limits、errors 和 golden fixtures 移至仓库级 `contracts/agent-runtime/`，作为 Worker 与 Python Runtime 的共同事实源。Python validators、Dockerfile COPY、测试和协议生成/校验脚本全部改用新路径；先完成等内容迁移并验证 hash/fixture，再删除 TypeScript 生成器和产物。

协议仍保留 runtime kind、protocol version、invocation、digest、Publication/hash、模型连接、事件、取消和唯一终态字段。当前支持的历史协议版本继续可读取；本变更不借机重写协议语义。

### 6. 模型连接探测迁移到 Python Runtime

现有 API 的 RBAC、限流、HTTPS/host/IP/redirect SSRF 校验保持在控制面，随后把固定 revision/config hash 的无工具、单轮、短超时 probe 委托给 `python-agent-runtime`。Runtime 内继续解析 active Secret、隔离调用环境、限制输出并返回脱敏版本/host/model/耗时/稳定错误码。

探测 API 不再接受 Runtime 选择；历史响应中的 runtime provenance 仍可显示原值。readiness 只聚合 Python Runtime，不调用 Provider 或 MCP。

### 7. 删除双实现，但保留所有安全边界

Python Runtime 必须继续通过部署固定的 `tool-mcp` 与 `file-service` 调用 Job 冻结 Tool；保持空自动批准集合、逐次权限回调、危险工具拒绝、Job Sandbox 路径守卫、Principal JWT、流式文件传输、Secret 隔离、日志脱敏和有界事件。删除 TypeScript parity tests 后，以 Python 合同测试和新鲜 Compose E2E 覆盖这些行为。

### 8. readiness 与部署不再被已删除服务耦合

Compose、API、Worker、Webhook/Channel worker 和运维脚本删除 `typescript-agent-runtime` 依赖、URL、allowed host、Secret mount 和网络声明。`/api/ready` 报告 `python-v1` 为唯一支持 Runtime，并继续区分“配置/依赖 ready”与“模型/MCP 未被健康检查调用”。

## Risks / Trade-offs

- [Python SDK 缺少当前 TS 路径中的行为] → 删除服务前以相同协议 fixture、真实 CLI callback、模型 probe、MCP、文件工作区、取消与终态恢复做 focused regression；缺口必须先补齐。
- [其他环境仍有 TypeScript Job 或活动 Deployment] → 每个环境运行只读预检；任一非终态 Job、活动引用或待处理队列消息都会阻止删除阶段。
- [错误地改写历史 provenance] → 保留数据库历史值和只读 API 投影，禁止 backfill `typescript-v1` 为 `python-v1`，迁移只创建新 Publication。
- [合同随 TypeScript 目录一起被误删] → 先等内容迁移到仓库级路径并运行 schema/golden 校验，再删除 TypeScript 源码。
- [回滚时旧应用指向不可用 Runtime] → contract schema 不在本变更中收窄；删除阶段前保留可重建的镜像版本和部署清单，回滚需同时恢复 TypeScript service 与旧应用 activation。
- [单 Runtime 成为单点故障] → 通过同一无状态镜像横向扩容、Runtime Grant、invocation ledger、readiness 和 Worker retry 提供可恢复性，而不是用异构实现做隐式 fallback。
- [维护成本下降但失去 TS SDK 新功能试验位] → 新功能先在 Python Runtime 内以受控升级/spike 验证；若未来确有第二 Runtime 业务需求，必须以新 capability 和明确运维预算重新提出。

## Migration Plan

1. **基线与预检**：备份目标数据库；按环境统计 TypeScript Definition、Publication、Application revision/deployment、各状态 Job、retry/outbox/queue 与审计引用；输出不含业务正文和 Secret 的报告。
2. **冻结新写入**：后端和前端只允许新建/发布 Python Agent；拒绝新 TypeScript Application Publication 与历史 TypeScript Application 重新激活；保留历史只读查询和暂时的 TS 执行兼容。
3. **能力对齐**：迁移 Runtime contracts；把模型 probe、协议、MCP、文件桥、沙盒、取消、恢复、审计与错误分类的验收集中到 Python Runtime。
4. **控制面切流**：为每个活动 TypeScript 引用创建新的 Python Agent/Application Publication，并通过显式 activate 切换；核对 hash、权限、Tool、文件和 Delivery 配置。
5. **排空门禁**：等待或确定性终结全部 TypeScript 非终态 Job，确认无可执行 retry/outbox/queue 消息；禁止通过 runtime kind 改写排空。
6. **删除运行面**：从 Registry、readiness、Compose、Dockerfile、脚本和网络中删除 TypeScript client/service，再删除 `agent-runtime/` 的 Runtime 实现、Node lockfile 与双 Runtime tests。
7. **验证与观察**：执行 strict OpenSpec、迁移/schema checks、Python focused tests、前后端测试/build、镜像合同检查和使用合成数据的 Runtime→MCP/File→Job→Delivery 新鲜 Compose E2E；观察一个受控窗口后再宣布退役完成。

回滚分为两类：冻结/切流阶段可用新的 Application revision 显式切回旧 Publication，但仅在 TypeScript service 仍运行时允许；删除阶段若需回滚，必须恢复旧版本代码与 TypeScript 镜像/配置后才能重新激活旧 Publication。由于数据库历史值未被收窄或改写，回滚不需要伪造迁移账本。

## Open Questions

无阻塞设计问题。每个目标环境的 TypeScript 引用数量、非终态 Job 与队列计数属于实施期预检事实，未知或不一致时必须停止在对应迁移门禁。
