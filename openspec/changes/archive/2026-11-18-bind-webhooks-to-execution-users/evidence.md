# Webhook 执行用户验证记录

日期：2026-11-06；范围：本地 Compose 与合成输入，不代表其他环境已部署。

## 配置与行为

- Webhook v3 配置必选启用 human 执行用户，无独立角色或专用服务账号管理；保存草稿不修改运行索引，发布与回退同步索引。
- 应用 v8 使用 BOUND_USER，执行前检查事件身份与应用冻结身份一致；重新绑定后需要重新发布应用。
- 人员角色和外部身份未被更改；投递仍按每个入口独立配置，执行人员与收件人分离。
- 个人工具继续执行现有身份、来源渠道和确认门禁；本次没有扩展钉钉个人 MCP 的来源 Connector 规则，没有测试或自动确认个人写入。

## 自动验证

- Webhook、业务应用、知识授权、渠道投递相关后端回归：241 项通过。
- 增加应用冻结用户与事件用户不一致的拒绝回归后，Webhook 接入与渠道投递 22 项通过，包含新增回归。
- 钉钉企业治理与测试数据重建：13 项通过；统一身份 RBAC：5 项通过。
- 前端应用域 5 个测试文件，34 项通过；TypeScript、ESLint、Ruff、构建、OpenSpec strict 与 diff whitespace 检查通过。
- 独立 PostgreSQL 18 容器验证全新 schema/comment 合同，以及 157 → 158 升级、旧入口明确解绑停用、人员保留和重复执行。
- 隔离 PostgreSQL 容器及其匿名数据卷已删除，仅清理本次创建的验证资源。

## 真实本地链路

- 升级前确认没有 PENDING/RUNNING/WAITING_APPROVAL Job；迁移到 158，并更新 API、Webhook/渠道/Job/投递 Worker、两份 Agent Worker、MCP/文件/知识消费者及管理端。
- test-webhook 发布 r4 绑定 Administrator（admin），入口定义 r12 已启用。
- assist03 发布并激活 r65，schema v8，运行状态 wired/ready；三条入口和三条投递保持原对应关系，钉钉目标人员保持一人。
- 新合成事件 manual-test-execution-user-20261106-001 收到 HTTP 202。
- Event：webhook_event_fbe13342a43744939800f59ba46743a6，状态 JOB_CREATED。
- Job：job_f5b2d638d82f4f658ac43fcb957eb917，执行用户 admin，状态 SUCCEEDED；未再次发生 knowledge_job_denied。
- 对应 delivery_outbox 一条记录为 SUCCEEDED。此为平台投递成功记录，不代替收件人阅读确认。
- Chrome 实际页面确认“执行用户”回显 Administrator，并可选择启用人员 admin、liqh、zmh-iphone；没有业务角色或服务账号配置控件。核验专用标签页已关闭。

未重放历史失败事件；未验证其他个人工具的真实 Provider 调用。
