# 重复测试与热点重构审查

## 已完成结构调整

- 原 `backend/tests/helpers.py` 从 802 行实现文件收敛为阶段性兼容导出
- 新增领域支持模块：runtime、applications、authorization、channels、delivery、file-workspace
- 业务应用控制面直接使用 Authorization/Channel builder
- 角色授权直接使用 Application MCP Tool builder 和 Delivery builder
- Python Runtime 直接使用 Runtime builder
- 连续多模态与任务文件合成验收共享 File Workspace builder，不再从另一个测试文件导入 fixture 实现
- 钉钉企业身份、未知主体拒绝、Callback 不创建 Job 和 Secret 不泄漏链路从 RBAC 契约文件拆到独立 acceptance 文件
- Agent Profile 前端测试开始使用共享 JSON response 与 QueryClient render 工具

## 重复测试审查结论

本阶段没有删除测试。以下表面重复仍覆盖不同边界，因此保留：

- SQLite 与 PostgreSQL migration：分别覆盖方言、ledger、advisory lock、中文注释及 schema 等价，不等价
- Admin API 授权拒绝与 Runtime 授权拒绝：入口主体、审计事件和副作用边界不同，不等价
- Outbox 重试、Worker DEAD 和 Delivery 恢复：状态机、幂等键和恢复责任不同，不等价
- 私聊、群聊、Webhook 与 Debug Job：Session key、当前主体、Routing Key 和投递绑定不同，不等价
- File Workspace synthetic、group acceptance 与低层 repository/manifest：完整链路证据和领域契约证据层级不同，不等价

## 删除门禁

后续删除候选必须在 evidence 中列出：原测试、替代测试、canonical Requirement、正常路径、拒绝路径、恢复路径、审计边界和 Secret 边界。本阶段没有满足全部等价条件的删除候选。
