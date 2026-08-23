# 03 领域模型

## 身份与授权

- `app_user`、`user_external_identity`
- `rbac_role`、`rbac_user_role`
- 角色的管理后台能力、业务应用访问、MCP Tool identifier 和数据范围
- ONES identity challenge、Team、默认 Team，以及 purpose-bound AES-GCM 加密的当前
  `external_identity_credential`

## 发布

- Agent Definition -> Revision -> Publication -> MCP Tool Envelope
- Business Application -> Revision -> Publication -> Deployment
- Application Publication 的 MCP Tool 必须是 Agent Envelope 的显式子集

## 工具资源

- Resource Identity -> Draft/Verified/Published Revision
- Resource scope：environment，可选 base/workshop/placement
- Secret Ref 指向平台 Secret，明文不进入发布快照

## 执行历史

- Agent Session、Job、MCP Tool Snapshot、Tool Call
- Runtime Invocation/Event/Terminal Ledger
- Task Workspace、File/Version、Catalog Revision、Working Set、Manifest v5、Representation
- Artifact、Delivery Outbox/Attempt、Audit Event 与 MCP Operation Audit

Job 不冻结用户消息中推断出的工具目标；目标只在实际 Tool Call 参数中出现并实时鉴权。
