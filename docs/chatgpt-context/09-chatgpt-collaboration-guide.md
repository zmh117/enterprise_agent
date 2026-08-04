# ChatGPT 技术协作指南

## 建议作为 Project Instructions 的内容

可以把下面内容复制到 ChatGPT Project 的自定义指令中：

```text
你是 Enterprise Agent 项目的架构与工程协作助手。默认使用中文，直接、技术准确。

每次回答前先区分：
1. 当前代码已实现；
2. OpenSpec/ADR 已设计但未完全验收；
3. 纯建议或待确认假设。

不要因为 proposal、design、task 或页面原型存在，就声称运行能力已完成。需要当前事实时，要求提供对应代码、migration、OpenSpec status、测试、readiness、数据库或业务 E2E 证据。

必须保持以下架构边界：
- PostgreSQL 是事实源，RabbitMQ 只传稳定 ID；
- Draft -> Validate/Test/Verify -> immutable Publication/Revision -> explicit activation；
- Job 固定精确发布版本，但关键阶段实时复核撤销；
- Business Application 装配 Agent、入口、Capability 子集、会话和 Delivery；
- 内置只读工具与受治理 API Capability 是两类不同 Tool；
- 不建议任意 URL、SQL、MCP、Shell、脚本、模板或通用执行器；
- 外部身份、个人凭据、默认 Team 和平台授权必须分离；
- 外部 API 第一版使用 CURRENT_ACTOR，不回退共享账号；
- 原始外部响应不持久化，只保留有界规范化输出；
- Delivery 重试不能重新运行 Agent；
- 无匹配应用、身份、权限、凭据或发布版本时必须 fail closed。

涉及方案设计时，至少说明：领域边界、数据模型、状态机、权限主体、Credential Subject Policy、发布快照、迁移、Outbox/幂等/重试、敏感数据边界、回退和验收证据。

涉及 Host、username、Secret、Token、密码、模型 Key 或数据库账号变化时，不要自行假设；先解释对象差异、影响范围并要求明确确认。永远不要要求用户上传或粘贴真实 Secret。

默认选择稳健方案，不以“最小改动”为唯一目标。发现旧 OpenSpec 与当前代码重叠或矛盾时，先指出并建议归档、同步或重写，不要叠加第二套实现。
```

## 推荐首轮提示词

```text
请完整阅读上传的 Enterprise Agent 上下文包，并先输出一页“你理解的系统边界”：

1. 用一句话定义系统；
2. 画出控制面、入口、Job、Agent、Tool 数据平面和 Delivery 的关系；
3. 列出五条不能破坏的安全不变量；
4. 区分当前已实现、部分完成和规划中；
5. 指出你需要我补充的源代码或现场证据。

这一步不要提出大规模重构，也不要假设 OpenSpec task 全部已完成。
```

## 讨论新功能的提示词模板

```text
我要讨论的能力是：<能力描述>。

请基于现有架构做方案探索，先不要写代码。输出：
1. 它应属于哪个 bounded context；
2. 与现有 Agent、Business Application、Channel、Tool Resource 或 API Capability 的关系；
3. 至少两个方案及权衡；
4. 推荐方案的数据模型、状态机和 API 边界；
5. 身份、权限、Credential Subject Policy 和数据分级；
6. Draft/Verify/Publish/Activate 与 Job snapshot 语义；
7. Migration、Outbox、幂等、重试、回退和审计；
8. 自动化、Compose、数据库、浏览器和真实外部 E2E 验收；
9. 需要新增或修改的 OpenSpec/ADR；
10. 当前仍需我确认的规格问题。

不要建议任意代码、URL、SQL、Shell 或动态 Tool executor。
```

## 评审现有实现的提示词模板

```text
请评审以下实现／diff：<上传文件或粘贴脱敏 diff>。

按严重级别列出问题，优先检查：
- 是否误把草稿或最新配置用于运行；
- 是否绕过 Business Application route 或发布快照；
- 是否混淆内部用户、外部身份、个人凭据和授权；
- Job create / worker start / tool call / delivery 是否 fail closed；
- 是否出现任意 URL、跨 Origin redirect、任意 SQL/脚本或 Secret 泄漏；
- Inbox/Outbox、幂等、retry/dead/replay 是否可靠；
- 原始 payload/外部响应是否进入数据库、队列、日志、审计或模型；
- 是否有 migration、回退和真实 E2E 缺口。

每条结论标注证据文件；无法确认时写“待验证”，不要猜测。
```

## 故障诊断提示词模板

### 钉钉无回复

```text
请按 Runtime -> Channel Inbox -> Channel Outbox -> Job -> Worker -> Tool -> Artifact -> Delivery 的证据链诊断。

我会依次提供脱敏的：
- docker compose ps；
- Runtime/worker 安全日志摘要；
- event、outbox、job、tool-call、delivery 状态和 correlation ID；
- readiness 与队列计数。

不要仅凭容器 healthy 下结论，不要要求 Client Secret、Token、消息正文或 Session Webhook。
```

### Tool 不可见／不可调用

```text
请依次核对 Job -> Agent Publication -> Application Publication -> Release/Handler/Resource -> 当前用户身份/default Team/credential -> execution binding。

区分：代码未注册、应用未发布、用户前置条件缺失、运行时禁用和外部系统失败。不要把隐藏 Capability 误报为平台没有 Tool。
```

### Internal API Platform 不健康

```text
请区分 database、schema head、Master Key、service token、runtime assembly、published/effective generation、resource state 和 application binding。

先做只读诊断；不要自动修改 resource Host、username 或 Secret，也不要用 YAML fallback 掩盖无效 DB 配置。
```

## 让 ChatGPT 输出方案时的期望格式

优先要求以下结构：

1. **结论**：推荐什么，为什么；
2. **现状证据**：当前代码／迁移／OpenSpec 哪些已存在；
3. **领域边界**：新增或修改哪些模块；
4. **架构图／时序图**：只在关系复杂时使用；
5. **数据与状态**：对象、约束、状态机、幂等键；
6. **安全**：主体、凭据、授权、数据分级、fail-closed；
7. **发布和迁移**：兼容、切换、回退；
8. **验收矩阵**：单元、集成、PostgreSQL、Compose、浏览器、真实 E2E；
9. **Open questions**：必须由业务／用户确认的规格。

要求 ChatGPT 给每个重要判断标记为：

- `Confirmed-current`：已由当前代码／现场证据确认；
- `Documented-intent`：来自 ADR／OpenSpec，但未确认完成；
- `Inference`：基于证据的推断；
- `Proposal`：新建议。

## 建议按主题追加上传的文件

### 讨论身份与授权

- `CONTEXT.md`
- `docs/unified-identity-rbac-admin.md`
- `docs/adr/0031-reuse-external-identity-panel-with-self-and-admin-modes.md`
- `docs/adr/0039-derive-dingtalk-application-access-from-route-and-enabled-user.md`
- `backend/app/modules/identity/`
- `backend/app/modules/authorization_center/`

### 讨论 Agent 与业务应用

- `docs/business-application-control-plane.md`
- `docs/agent-profile-model-connections.md`
- `backend/app/modules/agent_config/`
- `backend/app/modules/business_application/`
- `backend/app/modules/job/application/create_agent_job_service.py`

### 讨论 API Capability

- `docs/governed-api-capabilities.md`
- `docs/adr/0001-0048` 中相关 ADR
- `backend/app/modules/api_capability/`
- `backend/migrations/025_governed_api_capabilities.sql`
- `openspec/changes/add-governed-api-capability-handlers/`

### 讨论 DingTalk／Webhook

- `docs/web-managed-multi-dingtalk-runtime.md`
- `docs/webhook-agent-triggers.md`
- `backend/app/modules/managed_channel/`
- `backend/app/modules/webhook/`
- `dingtalk-runtime/src/`

### 讨论内部工具平台

- `docs/internal-api-platform.md`
- `backend/app/modules/internal_tools/`
- `backend/app/modules/internal_api_platform/`
- `backend/app/modules/platform_config/`
- `backend/migrations/022_governed_tool_resource_versions.sql`

### 讨论可靠性与部署

- `docker-compose.yml`
- `backend/app/modules/job/domain/job_dispatch.py`
- `backend/app/modules/delivery/domain/delivery_outbox.py`
- `backend/app/workers/`
- `openspec/changes/stabilize-platform-runtime-foundation/`

## 上下文刷新提示词

仓库更新后可以发送：

```text
这是上次架构上下文之后的新提交、migration、OpenSpec status 和测试／readiness 证据。

请只做增量更新：
1. 哪些 Confirmed-current 事实变化；
2. 哪些 Documented-intent 已变成已实现；
3. 哪些旧假设或 change 已过期；
4. 哪些架构图、状态矩阵和风险需要修订；
5. 是否出现违反既有设计决策的漂移。

不要复述未变化内容。
```

## 数据安全提醒

适合上传：

- 源代码、接口 schema、迁移、ADR、OpenSpec、脱敏日志摘要；
- 假 ID、hash、错误码、状态和数量；
- 不含业务正文的 correlation 证据。

不适合上传：

- `.env` 和任何真实 Secret；
- Client Secret、Token、密码、模型 API Key、Cookie、CSRF；
- 数据库 DSN／真实账号密码、Session Webhook、完整 Authorization Header；
- 原始钉钉／Webhook payload、内部日志正文、真实个人信息；
- 外部 API 原始响应或未经授权的 INTERNAL 数据。

如需讨论敏感现场问题，先在本地生成脱敏摘要，再上传摘要和稳定 ID。
