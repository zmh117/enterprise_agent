# 项目总览

## 一句话定义

Enterprise Agent 是一个面向企业内部的、以只读诊断为核心的 Agent 应用控制与运行平台：管理员通过控制面组合业务应用、Agent 发布版本、渠道、工具资源和受治理 API 能力，消息发送者则在自己的身份、角色、应用和数据范围内触发异步诊断任务并接收结果。

它不是一个简单的钉钉聊天机器人，也不是允许管理员任意编写 URL、SQL、Shell 或脚本的通用自动化平台。

## 要解决的问题

企业诊断场景通常同时包含以下复杂性：

- 用户从钉钉私聊、群聊、Webhook 或调试入口发起请求；
- 每条请求必须绑定真实内部主体，而不能把群、机器人或外部账号直接当授权主体；
- Agent 需要访问日志、数据库、Redis、ER/业务流上下文或外部业务系统；
- 数据访问必须只读、有界、按环境／基地／车间隔离，并留下审计证据；
- Agent、应用、模型、工具、外部 API 和投递目标需要可版本化、可验证、可回滚；
- 长耗时执行、入口重投、RabbitMQ 故障和 Delivery 失败不能导致任务丢失或重复执行业务逻辑；
- Secret、Token、密码和外部原始响应不得进入模型上下文、普通日志或管理页面。

平台把这些问题拆成控制面、异步执行数据面、内部数据平面和渠道适配层，而不是把所有职责塞进 Agent executor。

## 当前核心能力

### 控制面

- React 管理控制台和 FastAPI 管理 API。
- 统一内部用户、Web Session、角色与授权中心。
- 钉钉外部身份、ONES 身份和个人外部 API 凭据治理。
- Agent Definition → Draft Revision → immutable Publication。
- 模型连接配置、测试、版本化和加密 API Key 轮换。
- Business Application 草稿、校验、发布、环境激活和历史回退。
- 钉钉应用机器人、Webhook Trigger、平台 Secret、工具资源和 API Capability 配置。
- 运行记录、会话、Job、Tool Call、投递和审计查询。

### 数据面

- 钉钉 Stream、Webhook 和受控 Debug API 入口。
- PostgreSQL Inbox/Outbox 与 RabbitMQ 异步调度。
- Agent Job 状态机、持久化重试和终态失败通知。
- Claude Agent SDK／Anthropic-compatible 模型运行时；默认可使用 stub，部署显式开启真实模型。
- 两类模型 Tool：代码注册的内置只读工具，以及管理员配置但受固定 Executor 约束的 API Capability。
- 结果按原会话、钉钉企业机器人、Webhook、Email 或 `none` 等绑定投递。
- 连续会话与受限 Office/Markdown 附件处理。

### 内部只读数据平面

- 独立 Internal API Platform。
- 环境 → 基地 → 车间的结构化寻址。
- MySQL、SQL Server、Oracle 的只读 schema／SQL 网关。
- Redis `GET`／有界 `SCAN` 和 Loki 查询。
- SQL AST 校验、车间表前缀、只读账号、超时、行数和响应大小多层限制。

### 受治理外部业务 API

- API Connection 与 Authentication Profile 版本化。
- API Capability、Handler、Mapping Plan 和 Release 原子发布。
- 固定 `http-json-v1` Executor，不允许任意代码执行。
- 当前生产验收能力为 `cap__ones__work_item__search`。
- 每次调用使用当前消息发送者自己的 ONES 身份、默认 Team 和加密 Token，不回退共享账号。

## 明确非目标

当前版本不承诺：

- 通用写操作 Agent、任意脚本或任意 HTTP／SQL／MCP 执行器；
- 完整 Network Zone、CIDR allowlist、DNS rebinding 防护或通用 SSRF 防护；
- 多 ONES 实例、同一用户多个 ONES 账号、自动跨 Team 查询；
- Kubernetes、多运行环境发布、弹性伸缩或多区域容灾；
- 长期记忆、向量数据库、全文检索、自动保留期清理；
- PDF、旧 Office、压缩包、音视频、OCR、视觉理解和恶意软件扫描；
- Webhook 的生产级 HTTPS/HMAC/timestamp/nonce 全套边界；
- 业务写入型 Capability 或服务账号 Credential Subject Policy。

## 主要参与者

| 参与者 | 职责 |
| --- | --- |
| 平台管理员 | 管理人员、角色、Secret、资源、Connection、Capability 和系统运行状态 |
| 应用管理员 | 配置 Agent、业务应用、渠道、能力子集并执行发布／激活／回退 |
| 内部业务用户 | 通过钉钉或 Web 使用已授权应用，管理自己的 ONES 身份和凭据 |
| Webhook 服务账号 | 代表已发布 Trigger 在固定权限和数据范围内创建 Job |
| Agent Worker | 使用 Job 冻结的发布与授权事实执行模型和 Tool 调用 |
| Channel／Delivery Worker | 可靠接入外部消息并投递结果，不承担 Agent 决策 |

## 技术栈

| 层 | 技术 |
| --- | --- |
| Backend | Python 3.12、FastAPI、Psycopg 3、Pika、Cryptography、SQLGlot |
| Agent Runtime | Claude Agent SDK、Anthropic SDK、Anthropic-compatible Provider |
| Frontend | React 19、TypeScript、Vite 8、TanStack Query/Table、Base UI／shadcn、Tailwind CSS 4 |
| DingTalk Runtime | Node.js 22、TypeScript、`dingtalk-stream` SDK |
| Persistence | PostgreSQL 18 |
| Messaging | RabbitMQ 4 |
| Attachment Storage | MinIO／S3 private bucket |
| Delivery／Serving | Nginx、HTTP adapters、DingTalk adapters |
| Deployment | Docker Compose、一次性 Migrator、服务专用镜像 target |
| Specification | OpenSpec、ADR、Markdown 运行手册 |

## 仓库地图

```text
enterprise_agent/
├── backend/
│   ├── app/modules/          # 按领域模块拆分的 API/Application/Domain/Infrastructure
│   ├── app/workers/          # Agent、Job、Channel、Webhook、Delivery、Attachment worker
│   ├── migrations/           # PostgreSQL/SQLite 兼容迁移，当前 head 027
│   ├── seeds/                # 本地显式 seed
│   └── tests/                # 单元、契约、迁移和 opt-in 集成测试
├── frontend/src/
│   ├── contexts/             # 前端业务上下文
│   ├── app/                  # Router、Shell、Navigation
│   └── components/ui/        # Base UI / shadcn 组件
├── dingtalk-runtime/         # 固定 TypeScript 多 Client Stream Runtime
├── docs/                     # 运维文档与 ADR
├── openspec/                 # 主规格和活动 change
├── ones_mock/                # 本地 ONES 测试环境
├── scripts/                  # smoke、测试数据和运维脚本
├── docker-compose.yml        # 当前本地服务拓扑
├── CONTEXT.md                # 统一领域语言和关系
└── pyproject.toml            # Python 依赖和质量配置
```

## 当前成熟度判断

平台已经超出“原型 UI + 单 worker”的阶段：迁移、控制面、异步链路、发布快照、权限交集、两类 Tool、多个可靠 Outbox 和大量自动化验证均已落地。

但仍应定位为**本地／企业内网 MVP 与持续集成中的平台基础**，原因包括：

- 运行环境固定为 `local`；
- 多项真实外部链路验收仍依赖钉钉、Grafana、ONES 或模型凭据；
- 完整网络出口治理、Webhook 生产安全、长期保留和 Worker lease/fencing/cancel 尚未完成；
- 仓库级 mypy／format 质量基线仍有既有欠账；
- 多个 OpenSpec change 接近完成但尚未归档。

后续讨论应默认以“稳健平台演进”为目标，而不是回退到隐式全局配置、浮动最新版本或共享凭据。

## 关键源文件

- `backend/app/bootstrap.py`：依赖装配和生产／测试 runtime 差异。
- `backend/app/main.py`：FastAPI 路由注册、feature gate 和 readiness。
- `backend/app/modules/job/application/create_agent_job_service.py`：Job 创建与快照冻结。
- `backend/app/modules/agent/application/agent_executor.py`：Agent 执行边界。
- `backend/app/modules/agent/application/agent_context_builder.py`：Tool／Capability 暴露和上下文构建。
- `backend/app/modules/business_application/`：业务应用控制面和 runtime resolver。
- `backend/app/modules/api_capability/`：受治理 API Capability 全链路。
- `backend/app/modules/internal_api_platform/`：只读数据平面。
- `frontend/src/app/router/app-router.tsx`：当前管理端页面入口。
