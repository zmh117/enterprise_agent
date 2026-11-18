# Webhook 多接收人结果投递与停用验收

日期：2026-10-25；本地分支 `one_runtime`；本次实现与此前首次配置修复均未提交、未推送。新变更保持 active，尚未同步 canonical specs 或归档。

## 验收范围与结果

- 本地 Docker Compose 已重建并更新全部使用 backend/Dockerfile 的运行服务及 admin-web。PostgreSQL 迁移从 147 升级到 149（148 逐目标 Outbox，149 应用 webhook_result 类型）。升级前后原有 252 条 Delivery Outbox 均保留，原行 recipient_key 为空；新唯一约束已生效。
- 23 个运行容器、20 个已有健康探针均正常；无健康探针的 admin-web 与两个 agent-worker 均 running。
- `GET /applications/channels` 返回 200、`Cache-Control: no-store`；不存在的 `/assets/synthetic-missing.js` 返回 404。已打开旧页面需要重新加载。
- 原有凭据由数据库内计算记录指纹，仅导出指纹作比较；8 条平台密钥版本、3 条密码凭据、2 条外部身份凭据均未改变。未读取或输出真实凭据原文。详见 [credential-integrity.json](credential-integrity.json)。

## 自动化回归

1. Webhook 全组、Delivery Outbox 全组、钉钉客户端、业务应用控制面/运行路由：125 passed。之后增加的显式绑定三场景及无效用户回执回归包含在下面专组中。
2. 新增 `test_webhook_result_recipients.py` 专组：17 passed，覆盖有界 schema、重复/空/超量/URL/未知选项、Agent delivery 授权、普通 Stream delivery 继续禁止、两个接收人部分限流后独立恢复、重复 enqueue/消费、无效用户独立失败、绑定/Job 路线篡改、机器人停用、扇出事务回滚、Webhook→应用→Agent 合成执行→结果投递、旧 schema 147 数据升级/重跑/外键，以及应用绑定匹配/错源/重复。
3. 前端 applications/presentation：22 passed，包括混合群/用户配置、保存重开、删除、脏编辑停用、卡片停用。TypeScript/Vite production build、相关 ESLint、后端 Ruff、改动应用源码的 strict mypy、`git diff --check`、Compose 配置检查、严格 OpenSpec 校验通过。
4. 初次大组运行中，既有 SQLite 双 Dispatcher 并发测试出现一次 19/20 的时序失败；其单独复跑和随后两次整组回归通过，未修改该测试或弱化断言。这里不据此宣称生产吞吐量或端到端 exactly-once。

SDK/模型与钉钉网络边界：完整业务链使用仓库的合成 Agent Runtime；钉钉 adapter 使用真实请求构造器与 fake transport，验证群消息、单用户消息、限流和 invalidStaffIdList。没有向真实群或用户发送消息，没有真实 Provider 执行。外部成功但进程在记账前退出的重复窗口仍遵循现有投递语义。

## 实际浏览器与 Compose

独立 Chrome 会话 `ea-recipients-20261025`，全程使用合成操作员；未读取用户 Chrome 的 Cookie/密码。

- 从渠道页面创建 `synthetic-recipients-ui-20261025`，自动创建独立入口，无“必须选择已有 Connector”阻塞。
- 在配置页选择独立合成 Bearer 凭据引用与合成 Agent Publication，选择既有受管机器人引用，添加群和用户目标（全部为无实际收件人的 synthetic ID）。
- 保存、校验、预览、发布、启用通过；预览没有创建事件或 Job。
- 未保存消息模板编辑时执行停用成功，编辑保留；关闭重开可读取已保存接收人。
- 修改用户 ID，新增第二个合成群，再删除原群，保存、校验、重新发布通过。见 [接收人配置截图](recipients-configured.png)。
- 合成业务应用由后端服务准备空投递草稿；随后实际 Web 选择 `使用 Webhook 配置的接收人` 和该入口，保存、完整校验、发布通过。未激活该应用。
- 将且仅将这个合成入口 Connector 设为 disabled，渠道卡片直接“停用 Webhook”成功。见 [停用截图](webhook-disabled.png)。
- 停用后的合成 HTTP POST 返回 401 / `webhook_disabled`。本合成 Trigger 最终 Event=0、Job=0，未产生真实投递。

测试准备边界：合成操作员、独立合成凭据、Agent 的入口/投递绑定发布和空投递应用草稿通过后端服务准备；Webhook 创建、接收人编辑、校验/发布/启停以及应用投递类型的选择/发布由实际浏览器完成。未伪称所有前置步骤都来自 UI。

## 清理

合成 Webhook、入口、服务账号、操作员、Agent、业务应用及合成凭据均已停用；合成操作员密码删除、会话撤销。保留停用的合成配置作为可检查证据。既有机器人、密钥和用户凭据未更改。

浏览器按会话正常关闭，记录的 8 个助手进程全部退出，没有关闭用户 Chrome。见 [browser-cleanup.json](browser-cleanup.json)。Compose 继续运行。

## 使用方法

1. 强制刷新管理页，在“渠道与触发器 → 配置 Webhook → 结果投递”选择“钉钉机器人（多个接收人）”。每行选择机器人与群/用户；群填 openConversationId，用户填机器人所属企业内 userId；最多 20 项。
2. Agent 发布版本需分配这些机器人的投递权限。保存 Webhook 后校验、发布、启用。
3. 业务应用绑定此 Webhook 和同一 Agent Publication，投递类型选择“使用 Webhook 配置的接收人”，连接器选该 Webhook 入口；发布并激活应用，授权对应服务账号。旧应用已有单目标绑定不会自动替换。
4. 本地 Compose 的公开接收端口是 8000（8080 是管理页面），通用 JSON 的默认映射示例：

```sh
curl -X POST 'http://localhost:8000/webhooks/v1/<入口路由>' \
  -H "Authorization: Bearer $WEBHOOK_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"id":"event-001","message":"请分析这条告警"}'
```

`<入口路由>` 取配置页的 public ID；`WEBHOOK_TOKEN` 使用该 Webhook 对应的 Bearer 凭据。新事件使用不同 id，消息字段按保存的映射填写。HTTP 接收成功不代表 Agent 或消息投递已经完成，运行记录中逐目标查看状态。停用拒绝新请求和未创建 Job 的事件；已有 Job/Delivery 继续完成。
