# 本地实现与验收记录

日期：2026-11-06。范围：本地开发服务与合成测试，不代表真实模型或钉钉发送验收。

## 已实现

- Webhook schema 2 只保留固定适配器、Bearer 引用与业务角色。通用报文固定 `id` / `message`，保留 Grafana firing 告警。旧映射、Agent、投递、手填路由、可调限流不再接受新写入。
- 发布同步专用机器身份的角色，校验角色委派、启停及禁止后台管理权限。接收人与执行授权分离。
- Agent 入口候选只展示已发布启用的 Webhook。应用服务端校验所选 Agent 的入口范围，自动固定 Webhook 路由和机器身份。
- 接收事件记录应用与 Agent 发布版本；当前路由变更、角色权限撤销或来源失效时拒绝创建 Job。接收失败仅记录安全摘要。
- 应用选择启用的钉钉机器人及最多 20 名同企业已绑定人员。发布冻结身份，发送前重验人员、绑定和权限；按目标记录发送、失败和重试。空名单或没有投递配置使用 none。
- HTTP 回调保留在高级投递设置，只能使用受管出站 Connector 和安全目标标识。删除 `webhook_result` 入口。
- Agent 发布版本候选跨项目，仍固定到每个配置的当前有效发布版本。

## 验证

- Webhook、应用控制面、应用运行路由、渠道与投递相关回归：117 passed。
- 最后补充拒绝事件审计与候选异常处理后，受影响的接收、API、应用控制面和渠道回归：62 passed。
- 前端三组交互测试：21 passed，包含角色保存/重开、旧草稿限制、Agent 入口交集、多人/空名单和高级回调。
- Ruff、Mypy（45 个相关源文件）、前端 lint、生产构建与 `git diff --check` 通过。
- SQLite 从 156 升至 157 的旧事件保留、旧入口失效、拒绝事件空 Agent、外键及重复执行检查通过；新列中文注释覆盖检查通过。
- 独立临时 PostgreSQL 18 新建库迁移到 157 并重复执行通过，相关 PostgreSQL schema/comment 测试通过。临时容器已删除。
- OpenSpec strict validation 通过。

## 本地部署与界面

- 迁移前：2 个 Webhook 均为 disabled，活动 Webhook 路由为 0，没有排队/执行中的 Agent Job。历史 Webhook 发布被撤销，需按新表单保存并重新发布、启用。
- 已更新 API、管理页面与相关 Worker/MCP 服务，并统一两台 Python Runtime。`/api/ready` 返回 ready，schema_head 为 157，两台 Runtime 均 ready 且 prompt_status 为 MATCH。
- Chrome 实际页面确认：Webhooks 表单只显示凭据与业务角色；Agent 下拉同时提供 default-diagnostic-agent r48 和 mes-code-extractor r10；应用私聊投递显示启用机器人及多名已绑定人员；高级投递设置存在。
- 界面验证未保存或发布用户应用配置。用户已在验证标签页继续操作，保留该标签页。
- 未调用真实模型、未发真实钉钉消息，也未执行真实外部 HTTP 回调。端到端结果与逐目标发送使用合成输入及模拟 transport 验证。
