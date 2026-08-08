## Context

当前功能开关同时承担了三类不同职责：

1. 部署时决定管理后台、统一身份、RBAC 和业务应用控制面是否存在；
2. 决定已发布 Agent 是否执行、是否调用真实模型和真实内部工具；
3. 临时控制 Webhook、连续会话、附件和权限迁移等具体能力。

这些职责混在同一组 `FEATURE_*` 环境变量中，导致部署人员需要理解实现细节，并可能组合出“管理后台已开放但身份未启用”“业务应用已配置但 Runtime 不执行”等矛盾状态。另一方面，真实模型、真实工具和已发布 Agent Runtime 会产生外部调用、数据访问或费用，不能被一个管理后台总开关间接开启。

本变更涉及配置加载、数据库运行时配置、Bootstrap 依赖注入、管理后台认证、Webhook Worker、业务应用发布策略和运维诊断，必须保留 PostgreSQL、RabbitMQ、主加密密钥等 bootstrap 配置的现有边界。

## Goals / Non-Goals

**Goals:**

- 将普通部署人员需要理解的功能开关收敛为四个。
- 用一个管理面总开关保证 Web、统一身份、Web Session、RBAC 和业务应用控制面原子启停。
- 保留已发布 Runtime、真实模型和真实内部工具三个独立的数据面安全边界。
- 将 Connector、连续会话、附件和权限迁移等细粒度能力移动到可审计的领域配置。
- 提供单一、确定、可诊断的有效配置解析结果。
- 提供旧环境变量兼容期，并使冲突配置显式失败而不是静默猜测。
- 保证迁移本身不会自动开启真实调用、扩大权限或改变现有消息路由。

**Non-Goals:**

- 本变更不实现新的 Agent、Connector、连续会话或附件业务能力。
- 本变更不重新设计数据库、RabbitMQ 或 Secret 管理。
- 本变更不自动发布业务应用、Trigger、Connector 或 Agent Profile。
- 本变更不移除真实模型、真实工具和已发布 Runtime 的独立安全闸门。
- 本变更不允许管理 Web 修改 bootstrap-only 配置。

## Decisions

### 1. 对外只保留四个顶层功能开关

普通部署模板只展示：

| 开关 | 职责 |
|---|---|
| `FEATURE_WEB_ADMIN` | 管理后台总开关；派生统一身份、Web Session、RBAC 和业务应用控制面 |
| `FEATURE_PUBLISHED_AGENT_RUNTIME` | 是否允许已发布 Agent Runtime 消费并执行任务 |
| `FEATURE_REAL_CLAUDE` | 是否允许调用真实模型提供方 |
| `FEATURE_REAL_INTERNAL_TOOLS` | 是否允许调用真实内部 API 工具 |

`FEATURE_WEB_ADMIN=false` 时，管理 API 和管理前端均不可用；它不能影响钉钉接入、已发布 Runtime 或真实外部调用开关。`FEATURE_WEB_ADMIN=true` 时，管理入口必须完整启用身份和 RBAC，不提供“无认证管理后台”组合。

备选方案是保留所有旧开关但改进文档。该方案仍会暴露无效组合，无法从模型层消除运维复杂度，因此不采用。

### 2. 使用统一的有效功能配置解析器

后端引入不可变的 `EffectiveFeatureConfiguration`（具体命名可按代码规范调整），所有 API、Worker 和 Bootstrap wiring 只能读取该解析结果，不得各自直接读取 `os.environ`。

每个有效值至少包含：

- `key`
- `effective_value`
- `source`
- `classification`
- `deprecated_inputs`
- `restart_required`
- `diagnostics`

解析器先校验硬安全约束，再解析四个顶层开关，最后合并受治理运行策略。相同输入必须产生相同结果。

备选方案是在现有各模块中逐个替换判断。该方案会继续存在多套优先级和默认值，因此不采用。

### 3. 明确配置分类和优先级

配置分为：

1. **bootstrap-only**：`DATABASE_DSN`、`RABBITMQ_URL`、`APP_CONFIG_MASTER_KEY` 及服务启动前必须获得的网络/密钥参数；
2. **deployment safety gate**：四个顶层功能开关；
3. **governed runtime policy**：权限 shadow mode、业务应用的连续会话/附件策略、已发布 Connector/Trigger 状态等；
4. **test-only**：测试身份请求头等仅测试环境允许的设置。

优先级和安全规则如下：

- 硬安全约束优先于任何环境变量或数据库值；
- deployment safety gate 只能由部署环境开启，数据库配置不得越过关闭状态；
- governed runtime policy 来自已发布且有版本/审计的数据库配置；
- 数据库不可达时，不得把原本关闭的数据面安全闸门回退为开启；
- test-only 配置在生产环境设置为真时启动失败。

备选方案是继续允许数据库覆盖所有环境变量。该方案会让管理 API 绕过部署级安全边界，因此不采用。

### 4. 细粒度功能归还领域模型

- Webhook 接入由已启用 Connector、已发布 Trigger Binding 及其应用发布版本共同决定；
- 连续会话由业务应用或 Agent Profile 的已发布上下文策略决定；
- 附件接收与解析由 Channel 能力和业务应用的已发布附件策略决定；
- `permission_shadow_mode` 由带审计、版本和回滚能力的迁移策略配置决定。

这些策略必须使用现有草稿—发布边界；编辑草稿不得立即改变运行中行为。

备选方案是将旧全局开关原样搬入数据库。该方案只是更换存储位置，并没有把策略归还正确的领域边界，因此不采用。

### 5. 旧开关采用“一版兼容、冲突失败”

兼容版本识别：

- `FEATURE_UNIFIED_IDENTITY`
- `FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE`
- `FEATURE_WEBHOOK_TRIGGERS`
- `FEATURE_CONTINUOUS_CONVERSATION`
- `FEATURE_MESSAGE_ATTACHMENTS`
- `FEATURE_TEST_IDENTITY_HEADERS`
- `FEATURE_PERMISSION_SHADOW_MODE`

兼容规则：

- 仅配置旧开关时，适配器按旧行为生成兼容策略，并输出不含敏感值的弃用告警；
- 新旧配置表达相同结果时允许启动，但仍输出弃用告警；
- 新旧配置互相矛盾时启动失败并列出冲突键和迁移目标；
- 兼容适配不得开启 `FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE` 或 `FEATURE_REAL_INTERNAL_TOOLS`；
- 下一次明确的破坏性版本删除旧开关读取逻辑。

备选方案是“新值总是覆盖旧值”。该方案会隐藏部署错误并可能改变安全边界，因此选择显式失败。

### 6. 配置诊断只读且去敏

管理 API 和健康诊断提供相同的有效配置快照。快照显示值、来源、分类、弃用项、冲突和是否需重启，但不返回 Secret 明文、完整连接串或未脱敏环境值。

当管理后台关闭时，受认证的管理诊断 API 不对外暴露；服务健康检查仍提供机器可读的总体状态和错误代码，不暴露配置细节。

## Risks / Trade-offs

- [旧部署同时设置了相互矛盾的新旧开关，升级后无法启动] → 在发布前提供静态检查命令和 Compose 校验；错误信息给出具体迁移目标。
- [一个管理面总开关扩大了管理模块暴露面] → 强制统一身份、Session 和 RBAC 同时启用；不允许无认证降级。
- [将 Webhook/会话/附件下沉后，未发布策略导致功能不可用] → 迁移工具从当前有效配置生成草稿并要求管理员显式检查、发布，迁移过程不自动切换路由。
- [数据库运行策略不可用造成行为变化] → 使用最后一个已验证发布快照；无快照时采用关闭或只读的安全默认值，并标记 degraded。
- [环境安全闸门与数据库策略形成双层判断] → 诊断快照同时显示部署闸门和发布策略，明确最终结果与阻断原因。
- [兼容代码延长维护成本] → 兼容期固定为一个明确版本，并在任务和发布说明中列出删除点。

## Migration Plan

1. 增加有效功能配置解析器、分类元数据、冲突校验和只读诊断；原模块先通过适配层读取，行为保持不变。
2. 为权限迁移策略、上下文策略、附件策略和 Connector/Trigger 发布状态补齐持久化/读取边界。
3. 增加迁移检查命令，报告当前旧开关、对应新配置、冲突和待发布领域策略，不写入生产配置。
4. 管理员确认后创建或更新领域策略草稿并显式发布；先保持三个数据面安全闸门原值。
5. 将 Compose、`.env.example` 和运维文档收敛为四个顶层功能开关，同时保留 bootstrap-only 配置。
6. 兼容版本持续读取旧开关并输出弃用告警；生产启动和 CI 对矛盾配置执行失败校验。
7. 下一次破坏性版本删除旧开关读取逻辑和兼容测试。

回滚时恢复上一版本服务和原环境变量。迁移生成的领域配置使用新 revision，不删除旧 revision；未显式发布的草稿不会影响旧版本。任何回滚均不得自动开启三个数据面安全闸门。

## Open Questions

- 兼容期结束的目标版本号由发布计划确定，实施时必须写入运维文档和弃用告警。
- `permission_shadow_mode` 是否复用现有 runtime config 表，还是建立专用 RBAC migration policy，需要在实现前结合现有表结构决定；无论采用哪种方式都必须具备版本、审计和回滚。
- 连续会话和附件策略最终归属业务应用发布版本还是 Agent Profile 发布版本，需要根据现有领域模型选择唯一事实源，避免双写。
