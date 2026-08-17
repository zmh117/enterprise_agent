## Why

当前平台同时维护 Python 与 TypeScript 两套 Agent Runtime，但 Python 已是默认路径，2026-08-17 已核对的本地运行数据中 Agent Job 也全部固定为 `python-v1`。双实现要求模型调用、MCP、文件沙盒、协议、审计、错误分类、镜像和验收长期保持等价，维护成本与漂移风险已经高于当前未被实际使用的 TypeScript 灰度价值；其它目标环境仍必须在实施期重新预检。

## What Changes

- **BREAKING**：平台停止创建、发布、选择或激活新的 `typescript-v1` Agent 与 Business Application 配置，新执行统一固定为 `python-v1`。
- 将模型连接真实探测从 TypeScript Runtime 迁移到独立 `python-agent-runtime`，继续保持 RBAC、SSRF 防护、Secret 隔离、无工具、单轮和有界响应要求。
- 保留语言无关的 Runtime 协议、Worker/Runtime 进程隔离、Job 不可变运行快照和失败关闭语义，但生产 Runtime Registry 只注册 Python client。
- 分阶段停用现有 TypeScript Agent Publication 与引用它的 Business Application Publication；通过新的 Python Publication 显式替换，不原地修改任何历史快照。
- 删除 TypeScript Runtime 服务、Node 依赖链、Compose 装配、前端 Runtime 选择、双 Runtime acceptance 和重复实现。
- 保留历史 `runtime_kind`、TypeScript Publication、Job 与审计事实的只读可解释性；本变更不在同一发布中删除历史枚举值或不可变运行记录。
- 以 Python Runtime 的模型、MCP、文件工作区、取消、超时、重试、审计、Delivery 和合成 Compose E2E 作为退役门禁，容器健康不能替代业务链路证据。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`：将 Agent 创建、模型连接探测和管理界面从双 Runtime 收敛为仅支持 Python，同时保留历史 TypeScript 快照的只读语义。
- `business-application`：新 Application Publication 只能派生 Python Runtime，并禁止重新激活仍引用 TypeScript Agent Publication 的版本。
- `execution-delivery`：将真实执行、Runtime Registry、Worker、readiness 与 Compose 闭环从双 Runtime 收敛为独立 Python Runtime。
- `builtin-tool-resource`：将标准 Tool MCP 与 File MCP 的等价双 Runtime 契约收敛为 Python Runtime 单实现契约。
- `platform-operations`：删除 TypeScript Runtime 部署、Secret、沙盒和运维依赖，并为退役前检查、历史保留和 Python E2E 建立运维门禁。

## Impact

- 后端：Runtime kind 校验、Agent/Application 发布、Job 创建、模型探测、Runtime Registry、readiness、迁移/seed、历史投影和测试装配。
- Runtime：保留 `backend/app/python_runtime/`，删除 `agent-runtime/` 及 Python 到 TypeScript Runtime 的生产 client 路径。
- 前端：Agent Profile 和 Business Application 页面不再提供 TypeScript Runtime 选项，但历史详情仍能显示 `typescript-v1`。
- 部署：Compose、Dockerfile、环境变量、Runtime Grant、网络、健康依赖、脚本和运维文档收敛为单一 Python Runtime。
- 数据：现有 TypeScript Definition/Publication 与引用关系需要预检和显式迁移；历史事实不得被重写或静默映射为 Python。
- 验证：需要跨协议合同、Python Runtime focused regression、Compose 新鲜 Job、MCP、文件、retry、Delivery 与安全拒绝证据。
