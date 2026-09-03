## 1. 合同与回归基线

- [x] 1.1 为 `ones_create_bug` 增加失败优先的 Manifest/schema 测试，覆盖固定 identifier、`effect=mutation`、确认策略、`ones.task.create` operation、全部必填字段、可选额外关注者/来源元数据、`additionalProperties=false` 及 Provider/身份/Team 原始参数拒绝。
- [x] 1.2 为现有 ONES 只读 Tool、`ones_update_task` 和钉钉 mutation 建立不变回归，确认新增创建 Tool 不改变其 identifier、schema hash、effect、可见性、卡片或执行语义。
- [x] 1.3 为缺少必填字段、`null`、空字符串/空数组、未知来源类型、重复来源字段、任意 HTML、附件/关联/父任务/工时/迭代字段和非缺陷工作项请求增加合同拒绝测试。
- [x] 1.4 固化创建 Tool 的中文功能名、完整说明、写入标识和“仅钉钉来源且逐次确认”提示基线。

## 2. Action Intent提案链与状态迁移

- [x] 2.1 编写 additive migration，为 `external_action_intent` 增加 `proposal_chain_id`、`supersedes_intent_id`、`superseded_by_intent_id`、`superseded_at` 及必要索引/约束，并允许 `SUPERSEDED` 终态而不改写既有记录。
- [x] 2.2 扩展 External Action domain、repository 和 service，仅允许 `PENDING_CONFIRMATION -> SUPERSEDED`，并把新 Intent、旧 Intent CAS、互相引用、新卡 CREATE Outbox 与旧卡 UPDATE Outbox 放在同一事务。
- [x] 2.3 使用稳定 `mcp_call_id` 实现创建准备幂等：同一 Tool Call 重入复用原 Intent 与 Task UUID，不按相同标题或参数合并不同 Tool Call。
- [x] 2.4 校验 `supersedes_intent_id` 只能引用同 actor、Session、Application、Tool、ONES 身份和 Team 的待确认创建 Intent；旧 Intent 已批准、执行或终结时完整拒绝新替代卡。
- [x] 2.5 扩展确认回调、卡片状态渲染和 worker 扫描，使 `SUPERSEDED` 不可批准、不可执行且旧卡显示“已被新版本替代，请使用最新确认卡”。
- [x] 2.6 增加 migration/repository 并发和兼容测试，覆盖两个修订竞争、批准与替代竞争、重复回调、旧卡点击以及既有钉钉/ONES 更新 Intent 不变。

## 3. 创建字段目录与参数编译

- [x] 3.1 新增有界、版本化 `bug_create_field_catalog` schema、加载器、版本/摘要校验和生成一致性检查，只纳入本设计确认的固定缺陷类型、字段 UUID/type、中文标签及稳定静态选项。
- [x] 3.2 从 `查询条件字典.yaml` 和新增接口文档提取白名单内容及已知项目、人员、产品、模块、版本的名称到 UUID 索引生成运行 JSON，拒绝未知字段/type、重复或歧义名称、重复 UUID、影响/修复/验证版本混用，并确保运行镜像不包含或解析完整 mock 文档。
- [x] 3.3 实现完整创建参数规范化：所有必填字段、UUID/长度/数量边界、非空多选稳定去重、额外关注者及 `field_provenance` 固定字段/`current_message|conversation_context|field_catalog|ones_read` 来源枚举。
- [x] 3.4 实现固定 `add3` 编译器，生成顶层 `uuid/summary/assign/project_uuid/watchers`、固定缺陷类型、空 `parent_uuid/add_manhours` 和全部必填 `field_values`，同时生成标题/负责人双写及纯文本安全富文本。
- [x] 3.5 实现名称到 UUID 的目录优先解析器：文档唯一命中时直接使用，文档无唯一值时才调用代码固定只读接口；同时实现当前 ONES 用户强制关注、额外关注者去重、产品与模块关系、影响版本类型隔离及显示名称归一化。
- [x] 3.6 增加目录、全部字段映射、静态选项、文档命中不额外查询、文档缺失后查询、同名歧义、动态引用、多选去重、产品模块关系、关注者、富文本转义和禁止字段的参数化单元测试。

## 4. Provider预检、创建、回查与Mock

- [x] 4.1 扩展 ONES Provider 客户端，提供代码固定且调用方不可覆盖的项目/缺陷类型/创建权限/创建布局预检、动态引用验证、`POST .../tasks/add3` 和按冻结 Task UUID 回查 Operation。
- [x] 4.2 增加真实 adapter capability/readiness 失败关闭：缺少可靠创建权限、布局或 UUID 回查合同即拒绝正式 Intent，不以项目可见、成员身份或普通编辑权限替代。
- [x] 4.3 严格解析 `add3` 成功、明确 4xx、401 同身份受控刷新、409、超时、连接中断和非法响应，并只输出有界缺陷编号、Task UUID、状态及安全错误码。
- [x] 4.4 扩展独立 ONES Mock，提供权限/布局、项目与动态引用、固定缺陷类型、`add3`、按 UUID 回查以及可控 409/超时/连接中断/字段不一致场景，不依赖真实凭据。
- [x] 4.5 增加 Provider/Mock 合同测试，证明路径、Method、Header、Team 和认证只由受信配置与当前身份注入，Tool 参数无法改变请求目标或读取认证材料。

## 5. MCP准备、建议来源与确认卡片

- [x] 5.1 注册 `ones_create_bug` Tool 和 operation 元数据，仅接受可验证的钉钉私聊/群聊来源 RUNNING Job；Web、后台、无 Connector、无唯一原发起人或无兼容模板时在 Intent 前拒绝。
- [x] 5.2 在 Tool 说明和 Agent 使用约束中明确：所有字段必须完整，允许的建议来源仅为当前消息、当前相关会话/引用、版本化文档目录和本次 ONES 只读结果；名称解析先查文档、找不到唯一 UUID 才查接口，描述含“待补充”或引用歧义时只返回普通会话草稿，不调用创建 Tool。
- [x] 5.3 实现准备服务，依次复核 Job Tool Snapshot、Application/角色授权、原 ONES 身份/Team/Credential、固定缺陷类型、创建权限/布局、目录和动态引用，再生成一次 Task UUID、冻结业务快照并原子创建 Intent/Card Outbox。
- [x] 5.4 扩展 ONES 卡片渲染器复用 `external_action_confirmation` 的既有四字段合同，以固定顺序完整展示全部中文业务字段、当前及额外关注者、“建议值/系统固定/系统默认”标记，并隐藏内部 UUID/type、字段/type、HTML 和认证事实。
- [x] 5.5 对最终 `detailText` 实施 4000 字符硬预算，超限不创建 Intent；确认有效期固定 900 秒，过期 UUID 永久弃用，补充按钮只引导用户回当前会话。
- [x] 5.6 实现显式修订入口：只有可靠引用旧卡或 Agent 明确提交已验证 `supersedes_intent_id` 时进入同一提案链，其它相同会话/标题/参数均创建独立链。
- [x] 5.7 增加准备与卡片集成测试，覆盖完整建议、用户明确值、缺失/待补充、名称歧义、权限/布局不可用、私聊/群聊私发、Web 拒绝、卡片超限、过期、其他群成员点击、身份/Team 变化及修订替代。

## 6. 确认后执行、恢复与防重复创建

- [x] 6.1 在现有 `enterprise_agent-external-action-worker` 注册 `ones + ones.task.create` 执行适配器，复用全局 claim/lease、heartbeat、Card Outbox 和审计链，不新增服务或队列。
- [x] 6.2 实现执行前二次复核：原内部用户/钉钉主体、Job Snapshot、Application/角色授权、原 ONES 身份/Team、当前 Credential、目录摘要、创建权限/布局及全部动态引用任一变化均在写入前失败关闭。
- [x] 6.3 在 Provider 调用前持久化唯一 `STARTED` attempt、冻结 Task UUID、请求摘要和目录摘要；attempt 已开始后的恢复路径不得再次发送 `add3`。
- [x] 6.4 调用固定创建请求，并在明确成功后按同一 UUID 回查、逐项比较项目、缺陷类型、标题、完整描述、负责人、关注者和全部字段；全部一致才进入 `SUCCEEDED`。
- [x] 6.5 对 409、超时、连接中断、非法响应和 worker 中断只执行同 UUID 回查；一致则“核验后成功”，不存在、不一致或不可核验则进入 `FAILED_UNCERTAIN`，禁止换 UUID 或自动重放。
- [x] 6.6 更新原卡结果：成功显示缺陷编号、标题、项目、负责人及受信配置生成的查看链接；失败/不确定只显示中文安全原因和关联号，不展示内部 UUID 或 Provider 任意 URL/原文。
- [x] 6.7 增加执行与恢复集成测试，覆盖确认后撤权/换绑/Team 变化/布局漂移、明确成功、明确失败、409、超时后成功核验、字段不一致、回查失败、双 worker 竞争、lease 恢复和重复消息不重复创建。

## 7. 审计、发布授权与管理界面

- [x] 7.1 扩展 Action Intent/MCP/Provider 审计，保存完整确认业务快照、中文显示值、建议来源类别、actor、绑定 revision、预检、卡片动作、attempt、请求摘要哈希和白名单结果，并拒绝持久化原始会话、私有推理、Token、JWT、Cookie、Header、Credential 或原始 Provider body。
- [x] 7.2 在授权中心和 Agent/Application Tool 列表中增加“创建 ONES 缺陷 `ones_create_bug` / 完整说明 / 写入”，明确仅钉钉来源、逐次确认和真实 Provider 未就绪状态。
- [x] 7.3 验证注册 Tool 不自动授予现有角色、不修改既有 Agent/Application Publication、不扩大当前或历史 Job；只有显式新授权、新发布及之后的新 Job 能冻结该 Tool。
- [x] 7.4 增加管理 API/UI、schema hash、未知确认策略、未发布 Tool、真实 adapter 未 ready 和安全审计读取权限回归。

## 8. 校验、构建与分层验收

- [x] 8.1 运行相关 `.venv/bin/pytest` 单元/集成套件、目标 mypy/前端检查、`git diff --check`，并如实区分本次失败与既有基线失败。
- [x] 8.2 验证 migration 从当前 head 升级、重复运行、schema runtime 投影和既有外部操作数据兼容，不执行破坏性降级。
- [x] 8.3 构建 backend、ONES MCP、dingtalk-runtime 和 external-action-worker 镜像并执行容器内 import smoke，确认裁剪镜像包含创建 adapter/目录但不包含 mock 文档或认证示例。
- [x] 8.4 运行 `docker compose config --quiet`、目标服务健康/并发检查和现有 ONES 查询/更新、钉钉 mutation 回归。
- [ ] 8.5 使用新测试角色、Agent/Application Publication 和新 Job 完成 Mock 全链：草稿补充、完整提案、私聊卡片、确认/拒绝/过期、修订替代、创建、回查、409/超时、未知结果及无 Secret 审计。
- [ ] 8.6 在取得真实 ONES 权限/布局/UUID 回查合同后完成真实 Provider 创建与异常核验；当前无真实服务时保持未完成，不以 Mock 替代。
- [ ] 8.7 使用真实钉钉私聊与群聊保存从 Job、Tool Call、Intent、卡片点击、Provider attempt 到结果卡片的完整审计证据；当前无真实服务时保持未完成。
- [x] 8.8 运行 `openspec validate add-governed-ones-bug-create --strict`，确认 artifacts 与最终实现一致后再进入 apply/sync/archive。
