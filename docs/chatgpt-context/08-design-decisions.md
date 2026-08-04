# 关键设计决策与防漂移规则

本文件不是愿望清单，而是当前架构已反复采用的决策。后续方案若要改变其中任何一项，应明确提出新的 OpenSpec／ADR、迁移路径、兼容边界、回滚和验收证据，不能在局部功能中顺手绕过。

## 1. 先做受治理的只读诊断平台

**决策**：第一阶段只支持不改变外部业务状态的诊断能力。

**原因**：企业数据访问、身份映射和模型不确定性已经足够复杂，写操作会引入审批、补偿、幂等、冲突、不可逆后果和更严格审计。

**结果**：数据库、Redis、Loki、ONES Capability 和 Agent 指令都必须保持只读；HTTP POST 只有业务语义为 `QUERY` 时才可能允许。

## 2. PostgreSQL 是事实源，RabbitMQ 只传稳定 ID

**决策**：Session、Job、Inbox/Outbox、retry、Delivery 和 Audit 以 PostgreSQL 为准；队列载荷尽量只包含 ID 和 correlation。

**原因**：broker redelivery、重启和 topology 迁移不能决定业务状态，也不能让正文、凭据或配置快照散落在消息中。

**结果**：恢复和对账先查 PostgreSQL；RabbitMQ 中断由 Outbox 恢复；不能新增一套只存在于队列中的 Job 状态机。

## 3. 草稿、验证、发布和激活分离

**决策**：可变 Draft 使用乐观锁；验证绑定 revision/hash；Publication／Revision 不可变；发布后还需显式激活或被上层选择。

**原因**：防止配置编辑直接改变运行，保留可审计历史和可靠回退。

**结果**：任何“保存后立即全局生效”的新功能都应被视为架构偏离。

## 4. Job 固定精确版本，不读取浮动最新配置

**决策**：Job 创建时冻结 Agent、Application、Model Connection、Capability、Handler、Resource 和执行策略 provenance。

**原因**：重试和长任务必须可重现，不能在执行中途因管理员发布新版本而改变语义。

**结果**：新版本只影响之后显式升级并创建的 Job；历史 Job 和 audit 不能被回写成新版本。

## 5. 冻结配置不等于绕过实时撤销

**决策**：Job 固定外部 User／Team 和配置版本，但 Worker start、Tool call、Capability call 和 Delivery 前仍检查当前用户、角色、身份、Token 和 Release 状态。

**原因**：配置可重现性与安全撤销必须同时成立。

**结果**：不能因为 Job 已创建就继续使用已停用用户、失效 Token 或被紧急禁用的 Capability。

## 6. Business Application 是装配与运行路由单元

**决策**：渠道、Agent Publication、可选 Workflow、Capability 子集、Session／Execution Policy 和 Delivery 由 Business Application Publication 统一装配。

**原因**：避免入口、Agent 和 Tool 各自维护隐式全局默认值。

**结果**：无活动 route 时失败关闭；不能回退 legacy default Agent 或另一个应用。

## 7. Agent 定义能力上限，Application 选择子集

**决策**：Agent Publication 冻结 Capability Envelope；Application Publication 只能从中选择精确 Release 子集。

**原因**：Agent 可复用，同时让每个业务应用只暴露最小能力集合。

**结果**：应用不能绕过 Agent 添加 Capability；Agent 新增能力不会自动进入既有应用。

## 8. 管理权限与业务运行权限分离

**决策**：配置／验证／发布 API 的管理 RBAC 不授予 runtime use；业务用户通过应用访问与能力子集获得调用资格。

**原因**：平台治理人员不一定是业务数据使用者，反之亦然。

**结果**：不要新增一个模糊的“Capability 全局 use grant”重复应用访问模型，也不要让平台管理员默认拥有所有业务应用权限。

## 9. 外部身份、个人凭据和平台权限分离

**决策**：Identity Binding 证明主体对应；External API Credential 保存 Token；默认 Team 定义外部范围；RBAC 定义平台访问。

**原因**：防止平台通过持久化密码代用户登录，或因“已绑定”自动越权。

**结果**：管理员不能代用户输入 ONES 密码；绑定失败、Token 失效和角色拒绝是不同故障。

## 10. 外部 API 默认使用当前消息发送人凭据

**决策**：第一版 Credential Subject Policy 仅支持 `CURRENT_ACTOR`。

**原因**：企业查询结果应受实际发起人的外部权限和 Team 限制。

**结果**：私聊和群聊不能回退共享 Token、管理员 Token、上次会话用户或服务账号。服务账号策略若未来需要，必须单独建模和审批。

## 11. 钉钉身份属于企业，不属于机器人

**决策**：DingTalk Enterprise 以 Corp ID 建立身份命名空间；多个应用连接共享企业内人员身份；应用观察只是来源证据。

**原因**：同一个人在同企业的多个机器人中不应形成多份身份，也不能把观察误当授权。

**结果**：身份唯一键是企业 + Staff ID；应用访问仍由命中的 Business Application route 决定。

## 12. 多钉钉 Runtime 使用固定进程内多 Client

**决策**：一个固定 TypeScript `dingtalk-runtime` 管理多个 SDK Client，通过 DB 配置和 reconcile 更新。

**原因**：避免控制面动态操作 Docker、修改 Compose 或为每个机器人创建容器。

**结果**：不挂载 Docker Socket，不动态创建容器；单 Client 失败不得阻断其他 Client。

## 13. 入口和 Delivery 与 Agent executor 解耦

**决策**：Channel／Webhook 标准化后统一进入 Job；结果通过独立 Delivery Outbox 和 adapter 发送。

**原因**：Agent 不应理解每种渠道 SDK，投递故障也不应重跑推理和 Tool。

**结果**：新增 Email、Teams 等 Connector 应扩展 adapter／contract，而不是修改 Agent 核心。

## 14. 可靠入口和投递使用 Transactional Outbox

**决策**：Channel、Webhook、Job Dispatch 和 Delivery 都先在同一数据库事务持久化业务事实与 Outbox。

**原因**：解决“DB 已提交但 MQ 未发”或“外部已发但状态未确认”的双写问题。

**结果**：新异步边界应优先复用 claim、lease timeout、retry、dead 和 replay 模式，而不是直接 fire-and-forget。

## 15. 内置只读工具与 API Capability 是两类对象

**决策**：内置工具执行实现由代码注册；外部业务 API 通过 Capability／Handler／Connection 受治理发布。

**原因**：内部诊断资源治理和外部业务 API 映射的风险、版本和认证模型不同。

**结果**：不能把 diagnostic Tool Catalog 包装成业务 API 页面，也不能让管理端修改内置 Handler 的可执行代码。

## 16. API Capability 拥有公开契约，Handler 只实现契约

**决策**：模型只理解 Capability Identifier、description 和公开 Schema；Handler、Connection、认证和 Mapping 是平台内部实现。

**原因**：隔离业务语义与传输细节，避免模型接触 host、Token、GraphQL 原文和系统字段。

**结果**：Agent／Application 只引用 Capability Release，不直接选择 Handler 或 Connection。

## 17. Handler 是受限声明式配置，不是通用执行器

**决策**：固定 `http-json-v1` Executor；相对路径、固定请求、受限类型化 Mapping；禁止脚本、模板语言和任意函数。

**原因**：管理员配置必须能静态验证、审计和限制，不能变成远程代码执行平台。

**结果**：任何“让管理员直接写 Python／JavaScript／Shell／任意模板”的建议都违背当前安全模型。

## 18. Capability Identifier 稳定且统一

**决策**：业务标识、模型 Tool 名、Agent／Application 引用和审计键使用同一 `cap__` 名称；版本由 Release revision 表达。

**原因**：避免点号转换、名称碰撞、版本后缀和多套映射。

**结果**：Schema 或实现升级通常保持 Identifier，创建新 Release；只有真正不同业务能力才创建新 Identifier。

## 19. 外部原始响应不持久化

**决策**：原始响应只在 attempt 内存中存在；Mapping 后丢弃；模型和数据库只接收有界 Normalized Output。

**原因**：降低凭据、敏感字段、提示注入和无界数据泄漏风险。

**结果**：排障依赖状态、大小、hash、安全错误码和受控预览，不能把原始响应写入审计“方便调试”。

## 20. 结构化寻址代替向模型暴露基础设施

**决策**：模型使用 environment/base/workshop 业务 code；Internal API Platform 解析真实 host、DSN 和 Secret。

**原因**：减少基础设施泄漏和任意目标访问，同时强制数据范围。

**结果**：`project_code` 不自动映射 environment；Agent 只能使用授权目录中存在的 code。

## 21. Read-only 必须纵深防御

**决策**：模型提示、Tool schema、SQL AST、表前缀、schema directory、只读账号、timeout、row/byte caps 和 audit 多层共同保护。

**原因**：单靠 prompt、HTTP GET 或字符串关键字都不足以保证只读。

**结果**：新增数据源必须定义方言级策略和真实只读账号要求，不能只加一个前端“只读”标签。

## 22. Secret 只通过受管版本解析

**决策**：Master Key 位于仓库外；Secret 加密保存；配置和发布只保存非敏感事实；attempt 解析 active version。

**原因**：支持轮换且不要求重发所有 Publication，同时避免 Secret 扩散。

**结果**：不要在文档、日志、Job snapshot 或 API 响应中保存 Secret ref／value；Key 泄露时轮换，不用回滚恢复旧 Key。

## 23. 对真实能力和验证证据保持保守表述

**决策**：代码存在、容器 healthy、自动化测试、fake SDK、真实外部 E2E 是不同证据层级。

**原因**：企业 Agent 的关键失败经常发生在身份、外部权限、网络和投递交叉处。

**结果**：没有真实 authenticated browser／DingTalk／ONES／Grafana 证据时，明确写“未执行”，不能用登录页、fake test 或配置状态冒充。

## 24. 破坏性操作必须独立、可恢复和二次确认

**决策**：身份重置、测试数据清理、旧队列删除等操作使用独立 CLI、只读 report、精确摘要、仓库外备份、固定确认短语和事务。

**原因**：普通 migration 或应用启动不能承担不可逆数据治理。

**结果**：不能把清理逻辑塞进 migration、seed、Compose up 或长期管理页面。

## 25. 延期能力不得通过模糊命名提前宣称完成

当前明确延期：完整 SSRF、Network Zone、Vault/KMS、Webhook replay protection、长期记忆、自动 retention、Worker fencing/cancel、多环境／Kubernetes、写操作 Capability、OCR／视觉／恶意软件扫描。

方案可以为这些能力预留边界，但不能把现有固定 Origin、Bearer、stored-only retention 或 runtime heartbeat 描述成它们已经实现。

## 方案评审的强制问题

任何重要新方案至少回答：

1. 属于哪个领域模块，为什么不是已有模块的职责？
2. 新增什么稳定对象、Draft、Revision、Publication 或 Runtime Fact？
3. 谁能配置，谁能使用，凭据属于谁？
4. Job 创建时冻结什么，运行时实时复核什么？
5. 如何防止外部 payload／模型覆盖 actor、scope、target 或 secret？
6. 需要哪些 migration、Outbox、幂等、retry、dead 和 replay？
7. 哪些数据能进入模型、数据库、日志、审计和导出？
8. 如何禁用、回退和恢复，历史证据是否保持不可变？
9. 自动化、容器、数据库、浏览器和真实外部 E2E 分别如何验证？
10. 哪些安全能力仍然延期，如何避免误报完成？

## 主要 ADR 入口

`docs/adr/` 中的 0001–0049 记录了受治理 API Capability、外部身份、发布快照、字段映射、当前 actor、Connection Origin、明文 HTTP opt-in 和 DingTalk 企业模型等决策。讨论具体决策时应上传对应 ADR 原文，不要只依赖本摘要。
