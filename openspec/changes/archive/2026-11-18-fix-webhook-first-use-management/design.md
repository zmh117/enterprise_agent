## Context

现场只读核对：运行库只有钉钉 Stream Connector，Webhook 定义数为 0。前端在候选入口为空时禁用创建，后端要求已有 connector_id；渠道卡片也没有 Webhook 编辑入口。现有 Trigger API 已覆盖草稿、校验、预览、发布和启停，可直接复用。

## Goals / Non-Goals

**Goals:** 首次创建不依赖 seed；可在渠道页面完成受管认证引用、映射、路由、Agent 发布选择、草稿校验、预览、发布和启停。保存草稿不影响当前发布，未发布不可启用。

**Non-Goals:** 不自动配置真实 Token、Agent 权限或业务应用授权，不新增任意 URL 执行器，不重写 Webhook 接收和调度协议，不提供公网或真实模型验收承诺。

## Decisions

1. 创建请求不指定 Connector 时，ManagedChannelService 在同一事务中创建 `managed_webhook` 入站专用 Connector，再调用既有 Trigger 服务创建专属服务账号及停用定义。每次新建独立入口，不复用钉钉或 Grafana 旧配置。失败整体回滚；保留显式已有 Connector 的内部 API 能力，但 Web 首次创建隐藏此实现细节。
2. `managed_webhook` 只允许 ingress，不另存认证 Token；认证唯一来源仍为不可变 Trigger Publication 中的受管 Secret 引用，未发布/未启用保持拒绝。无需新增表或凭据副本。
3. 渠道卡片新增配置面板，前端类型化 API 复用 `/webhook-triggers`。目录返回可选 Agent 发布，凭据通过现有凭据中心选择或输入受管引用。基础字段结构化编辑，变量/过滤和高级目标使用有界 JSON 输入。无权读取目录时显示真实错误。
4. 无结果投递使用 `type=none`、空 Connector 和空 target/options，校验及运行遵循原 none 语义；非 none 仍要求有效投递 Connector 和 Agent 授权。入口未分配给 Agent 时给出字段错误并引导先发布 Agent，不暗中扩大授权。
5. Web 展示保存的草稿 revision 与当前发布，修改未保存时禁止校验、预览和发布旧草稿。动作完成刷新详情与渠道目录。启停使用定义 revision；未发布禁止启用。公开路径与服务账号仅作配置引导，不把 202 或发布成功当作业务执行成功。

## Risks / Trade-offs

- [旧环境只有默认 Agent 或没有受管凭据] → 提供真实目录、空状态和配置指引，保留校验失败，不生成真实权限与凭据。
- [创建中途失败遗留 Connector] → 整个创建链同一 Unit of Work，覆盖失败回滚和重复编码测试。
- [前端保存与运行版本混淆] → 分开显示草稿、发布和启用状态；服务器发布重新校验依赖。
- [补齐 UI 暴露已有后端缺口] → 限定本变更为首次配置闭环，针对无投递和启用门禁作必要修正，不重构业务路由。

## Migration Plan

无需迁移与导入默认数据。部署 API 与 admin-web 后即可创建独立入口；已有 Connector、Trigger 发布和凭据保持原值。先在隔离环境使用合成账号、Token 和报文完成回归与构建，再按用户授权恢复本地 Compose、更新受影响镜像，并在实际部署的 Web 重复通用 JSON 配置闭环。部署验收使用独立合成账号、凭据和 Agent，通过数据库内聚合摘要比对既有凭据记录，不读取凭据明文；结束后停用合成入口和相关访问，保留发布、拒绝记录及审计证据。此次不执行真实业务或模型调用。

## Open Questions

无。用户已确认自动独立入口和 Web 完整配置方向。
