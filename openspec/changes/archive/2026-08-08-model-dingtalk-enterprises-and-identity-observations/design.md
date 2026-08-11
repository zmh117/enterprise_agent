## Context

当前 `user_external_identity` 使用 `(provider, tenant_code, external_subject_id)` 唯一定位外部身份，并在身份行上保存单一 `connector_id`。钉钉托管渠道则把管理员自由填写的 `tenant_code` 放入连接 metadata。这个结构在只有一个测试机器人时可以工作，但它把三件不同的事实混在了一起：钉钉企业身份命名空间、钉钉应用消息连接，以及内部用户的外部身份。

平台已经支持多个钉钉 Stream 应用连接、未绑定身份发现、人员详情治理模式和本人外部身份模式。真实 Stream 事件包含非空 `senderCorpId`、`chatbotCorpId`、`senderStaffId` 和 `senderNick`，因此可以从受信事件确认企业与身份，而不需要管理员手工填写钉钉用户字段。当前测试库中的旧钉钉身份、`default` 占位租户和连接器数据可以清理重建，但人员、ONES 绑定、Capability、Agent、业务应用主体以及所有历史 Job、Tool 调用和投递记录必须保留。

ONES 自助绑定已经采用服务端两阶段 Challenge，登录响应中能够取得用户名称以及 Team 的 ID 和名称；确认绑定后却只把 Team ID 保存到身份 metadata。个人凭据也缺少可直接支撑“最近成功使用”“最近失败”的结构化事实，当前页面因而只能展示固定租户、空连接器、Revision 和原始状态码。

本变更跨越 managed channel、DingTalk Stream、identity discovery、external identity、external credential、governed API runtime、管理端 API 和前端页面，需要先固定领域边界、状态机、写入顺序和重建策略。`docs/reference/decisions/0049-model-dingtalk-identities-by-enterprise-and-observation.md` 记录不可逆的核心模型决策。

## Goals / Non-Goals

**Goals:**

- 以真实 Corp ID 建立可审计的钉钉企业命名空间，并让多个应用连接引用同一企业。
- 将钉钉身份从单一连接器中解耦，通过应用观察记录表达身份经哪些应用出现过。
- 只允许受信候选形成新身份，正确处理同企业换绑、多企业身份、昵称乱序和历史恢复。
- 让本人和管理员看到业务可理解且权限适当的钉钉／ONES 身份字段。
- 为 ONES Team 名称、成功使用、失败尝试和调用来源提供真实持久化与运行时更新链路。
- 用非生产环境专用的一次性命令安全清理旧钉钉测试数据，同时保留跨域历史运行事实。

**Non-Goals:**

- 不增加逐钉钉应用的用户白名单，也不把应用观察记录解释为应用授权。
- 不支持同一用户绑定多个 ONES 实例或多个当前有效 ONES 账号。
- 不允许本人自助绑定、启停或解绑钉钉身份；钉钉身份仍由受信消息和管理员治理。
- 不在身份表复制钉钉消息正文、原始事件、Session Webhook、Client Secret 或其他认证材料。
- 不自动迁移旧钉钉测试身份，不扫描旧事件重建身份，也不删除任何 Agent Job、Tool 调用结果或投递记录。
- 不实现生产数据清理入口、定时身份清理或昵称手工编辑。

## Decisions

### 1. 钉钉企业、应用连接、外部身份是三个独立聚合

新增 `dingtalk_enterprise` 作为企业身份命名空间，使用内部 ID 供关系引用，并在验证成功后以真实 Corp ID 作为不可变外部稳定标识。`integration_connector` 中的钉钉 Stream 连接增加非空 `dingtalk_enterprise_id`，应用连接仍负责 Client ID、Client Secret 引用、运行心跳、接入和投递。

钉钉外部身份继续复用 `user_external_identity` 的公共生命周期和人员关联，但增加 `dingtalk_enterprise_id`，并删除钉钉身份上的 `connector_id` 所有权语义。对于 `provider=dingtalk`，唯一身份键为 `(dingtalk_enterprise_id, external_subject_id)`；同一个内部用户在同一个企业至多有一个 `enabled` 或 `disabled` 的当前身份。不同企业可以分别存在一个当前身份。

选择该模型而不是“每个应用各建一份身份”，因为 Staff ID 的业务含义属于企业，不属于机器人应用；重复身份会造成同一人的状态、昵称和应用访问彼此漂移。也不采用自由 `tenant_code`，因为拼写错误会静默制造新的身份命名空间。

### 2. 企业验证由首个应用的同一条受信消息完成

管理员先创建企业草稿并维护企业名称，再为其配置首个钉钉应用连接。企业初始为 `PENDING_VERIFICATION`，Stream 可以建立连接，但页面必须分别显示“连接运行状态”和“企业验证状态”，不得把 SDK `registered` 布尔值当成企业是否可用。

待验证连接收到通过 SDK 认证的测试消息时，服务端从同一事件提取非空 `senderCorpId` 与 `chatbotCorpId`，要求两者相等，并确认该 Corp ID 未属于其他企业。成功后在事务中固化 Corp ID、企业验证时间和安全审计证据，并将企业转为 `ACTIVE`。该测试消息不得创建身份候选、外部身份、应用观察、Application Access 或 Agent Job，也不得保存消息正文副本。

后续应用只能选择现有企业；其每条受信消息必须与企业 Corp ID 一致。缺失或不一致时拒绝消息、停止业务分发并产生不含用户内容和认证材料的治理告警。相比管理员直接填写 Corp ID，这一流程以受信运行事实校验配置；相比调用额外钉钉组织 API，它不增加新的权限和外部依赖。

### 3. 企业生命周期与连接运行态分别治理

企业状态固定为：

- `PENDING_VERIFICATION`：允许首个应用连接和收集安全验证证据，不允许业务消息、候选、身份解析或应用访问。
- `ACTIVE`：允许已启用且健康的应用连接正常处理消息。
- `DISABLED`：停止该企业全部应用入口和身份解析，保留所有企业、身份与观察数据。
- `ARCHIVED`：只读保留历史；只有全部应用均已停用时才能进入。

从 `DISABLED` 或 `ARCHIVED` 恢复时先回到待验证流程，应用必须重新连接并再次证明同一 Corp ID，不能只切换数据库状态。企业名称允许具备 `channels.manage` 的管理员修改并通过公共治理审计记录修改人、时间和前后名称；已验证 Corp ID 没有通用编辑接口，归属错误只能停用原企业并重新接入。

连接的 `CONNECTED`、`RECONNECTING`、心跳和错误状态仍由 runtime 管理，不改变企业生命周期。企业 `ACTIVE` 也不保证每个应用连接当前健康。

### 4. 身份与应用使用幂等观察记录关联

新增 `dingtalk_identity_application_observation`：

- `external_identity_id`
- `connector_id`
- `first_observed_at`
- `last_observed_at`
- 创建和更新时间

以 `(external_identity_id, connector_id)` 唯一，消息重试只推进 `last_observed_at`。记录不包含消息正文、Webhook、Client ID、Client Secret、原始事件或授权结论，并随身份历史长期保留。身份停用或解绑对企业下全部应用生效；某个应用是否允许某用户访问仍由独立 Application Access 策略决定。

人员详情技术区域按应用名称汇总观察记录和最近观察时间，不展示内部 Connector ID。排障人员需要 Connector ID 时进入对应应用连接配置或审计页面。

### 5. 昵称以受信事件时间单调更新并形成精简审计

钉钉身份的 `display_name` 作为当前钉钉昵称，增加 `display_name_observed_at`、`display_name_event_id` 和 `display_name_source_connector_id`。只有非空 `senderNick` 且 `(事件发生时间, 稳定事件 ID)` 晚于现有游标时才能更新；有效 `createAt` 经过格式和合理时钟偏差校验后作为事件时间，否则使用服务端接收时间。空昵称和旧事件不能清除或回滚新昵称。

每次昵称实际变化写入 `dingtalk_identity_nickname_audit`，只保存身份 ID、旧昵称、新昵称、事件时间、来源应用连接和稳定事件 ID。日常身份卡只显示最新昵称，本人不读取历史，管理员只能在审计视图查看。选择游标比较而不是按数据库处理顺序，可以抵抗 Stream 重试和乱序；保存精简审计而不复制原始事件，可以解释昵称变化而不扩散消息内容。

### 6. 新身份只来自已验证企业的受信候选

`dingtalk_identity_candidate` 使用 `dingtalk_enterprise_id + senderStaffId` 聚合，候选消息继续保存来源连接和有界安全摘要。手工输入 Staff ID、Corp ID、昵称或连接器的管理员绑定接口从产品和服务层移除。管理员在人员详情或发现页只提交候选 ID、目标用户 ID 和乐观锁版本，服务端重新读取候选及其企业、来源应用和当前状态。

绑定规则如下：

- 相同企业和 Staff ID 的历史身份只能恢复到原人员，不能转移给其他人员。
- 目标用户在该企业没有当前身份时，可以绑定候选。
- 目标用户在该企业已有不同当前 Staff ID 时，必须显式确认换绑；同一事务将旧身份软解绑并创建／恢复新身份。
- 目标用户在其他企业的身份不受影响。
- 企业或来源应用不再可用、候选版本过期、用户已停用或存在归属冲突时失败关闭。

### 7. 受信消息在创建 Job 前原子维护身份事实

钉钉消息的处理顺序固定为：

1. 解析应用连接及其企业，校验连接启用状态和事件认证。
2. 校验或完成 Corp ID 验证，并确认企业为 `ACTIVE`。
3. 用企业 ID 和 Staff ID 解析当前身份与内部用户状态。
4. 对已绑定身份在同一事务中幂等更新最近使用、应用观察和符合游标规则的昵称／昵称审计。
5. 计算 DingTalk Application Access、Application Publication 和后续 Capability 可用状态。
6. 持久化并分发 Agent Job。

身份事实写入失败时不得创建 Job。未绑定、停用或解绑身份转入候选分支，不更新正式身份观察；验证消息只形成企业验证证据。该顺序确保 Job 使用的身份和页面展示的来源证据一致。

### 8. 本人和管理员使用独立响应投影

后端使用本人 DTO 与治理 DTO，而不是把完整身份行返回后由前端隐藏字段。

钉钉本人摘要展示昵称、企业名称、状态和最近使用，可展开本人的钉钉用户 ID 与 Corp ID；不返回应用观察、Connector ID、Revision、昵称历史或治理动作。治理摘要展示同样的友好字段，并可展开用户 ID、Corp ID、绑定确认时间、Revision 和按应用名称汇总的观察记录。

ONES 本人和治理摘要统一展示 ONES 用户名称、综合可用状态、默认 Team、最近验证和最近成功使用。本人可展开 User ID 与全部 Team 名称／ID；治理 DTO 额外返回身份状态与 Revision、凭据状态与 Revision、Connection 名称和精确发布版本、最近尝试、最近错误码及时间。Token、密码、密文、认证 Header、Challenge 内部数据和固定占位字段永不进入这些 DTO。

### 9. ONES Team 候选和凭据使用事实由后端维护

确认 Challenge 时，把最新已验证候选保存为结构化 `teams: [{id, name}]`，同时保留单一 `default_team_id`。现有 ONES 身份非破坏转换：旧 `team_uuids` 转为名称为空的结构化候选，用户下次重新验证后以最新名称和集合整体替换；被 ONES 移除的 Team 不再可选。

`external_api_credential` 增加 `last_attempt_at`、`last_success_at`、`last_error_code` 和 `last_error_at`。解析出持久化个人凭据并真正开始外部请求时更新最近尝试；只有最终响应经过 Mapping Plan 和 Output Schema 校验后才更新最近成功。终态失败更新最近错误但不覆盖最近成功；成功不删除历史最近错误。登录／重新验证只更新验证时间，不算使用。

调用审计使用 `ADMIN_TEST` 和 `RUNTIME` 区分管理员 Capability Test 与 Agent 运行时。Connection 启动验证使用瞬时密码和 Token，不绑定持久化个人凭据，因此不更新这些字段。

### 10. 旧钉钉测试数据通过受保护命令清理

常规 schema migration 只增加和调整结构，不包含无条件删除。提供一次性 CLI，默认只做预检并输出：运行环境、数据库指纹、目标连接、各表数量、受影响应用渠道绑定、将撤销的 Secret 引用、明确保留的数据和 `plan_hash`。

执行必须同时满足：

- 环境明确为非生产；生产配置硬拒绝。
- DingTalk Runtime 与 ingress dispatcher 已停止，且不能取得新的相关写入。
- 操作者提交固定确认文字 `确认清空钉钉测试数据`、执行参数和预检 `plan_hash`。
- 事务内重新计算的数据库指纹、目标集合和数量与预检一致。

命令按外键顺序清理钉钉候选消息／候选、Ingress Outbox、钉钉 Ingress Event、Runtime 状态与租约、钉钉身份相关观察与审计、钉钉身份和企业；软删除旧钉钉应用连接、撤销其专属 Secret，并使其不再参与活动路由。历史 Application Publication 中的不可变连接引用不重写，只标记为不可运行历史来源；当前应用必须选择新连接并重新发布。平台人员、ONES、Capability、Agent、业务应用主体、所有 Agent Job、Tool 调用结果和投递记录均不删除。

执行中任一检查或删除失败则整体回滚。成功后输出实际数量和保留数据校验；命令重复执行返回空计划且不产生额外变更。相比把 `DELETE` 写进迁移，这一方案不会在未来正式环境自动清除真实数据。

## Risks / Trade-offs

- [首次企业验证依赖真实测试消息，配置步骤增加] → 页面提供明确的“已连接，等待企业验证”状态和测试指引，验证成功前不处理业务消息。
- [错误或恶意外部时间可能冻结昵称游标] → 校验时间格式和允许偏差，异常时间回退服务端接收时间，并以稳定事件 ID 保证幂等。
- [企业停用影响其全部应用] → 停用确认页列出受影响应用连接和业务应用，使用乐观锁与治理审计。
- [清理命令具有破坏性且清理后不能依靠代码回滚恢复身份] → 仅非生产、强制预检 Hash、固定确认文字、停止写入、事务执行，并在操作前保留数据库快照；恢复依赖快照或重新配置。
- [历史 Application Publication 引用已清理连接] → 不修改不可变发布快照，运行时明确判定其连接不可用，UI 标记历史来源，要求新连接重新发布。
- [结构化 Team 名称可能陈旧] → 只把最新成功验证结果视为可选集合；切换默认 Team 仍强制重新验证。
- [昵称和企业名称属于可识别信息] → 仅在必要身份与审计投影中保存，禁止进入普通日志、消息副本和未授权本人响应。
- [同一变更同时调整钉钉模型和 ONES 展示，范围较大] → 以独立 capability specs 和任务阶段拆分，先完成后端事实与接口契约，再调整页面和运行环境。

## Migration Plan

1. 为数据库创建可恢复快照，停止 DingTalk Runtime、Ingress Dispatcher 和相关 Outbox Worker。
2. 应用 schema migration：新增企业、观察、昵称审计和 ONES 使用字段，重建钉钉身份唯一约束；保留现有 ONES 身份和凭据。
3. 部署兼容新结构的后端和前端。未归属已验证企业的旧连接保持不可运行，不允许产生新 Job。
4. 运行重建命令预检，把数据库指纹、计划 Hash、删除数量、受影响应用和保留项交给用户确认。
5. 用户提供固定确认文字后，使用同一计划 Hash 在事务中执行清理并复核结果；不删除历史 Job、Tool 调用和投递记录。
6. 创建钉钉企业草稿，新增首个应用连接并录入 Client ID／Client Secret，启动 Stream 后发送测试消息完成 Corp ID 验证。
7. 通过新受信候选绑定人员，为业务应用选择新连接并重新发布，验证私聊、群聊、昵称更新、ONES Capability 和失败关闭路径。
8. 重启全部 worker，检查企业状态、连接心跳、Ingress、Job、Delivery 和 ONES 使用事实。

回滚分两类：执行重建命令前可以直接回滚代码和 schema；执行后代码回滚不能恢复已清理身份与 Secret，只能恢复操作前数据库快照，或保持新 schema 并重新接入。

## Open Questions

无。企业模型、身份基数、昵称时序、展示边界、ONES 字段和测试数据清理范围均已确认。
