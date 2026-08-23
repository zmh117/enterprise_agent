# agent-model Specification

## Purpose
定义 Agent、模型连接、工作流模板及 Agent 管理面的版本化配置、验证、发布与运行引用契约，确保草稿变化不会改写已冻结的执行配置。

## Requirements

<!-- Reconciled from mcp_new capability: `agent-control-plane-dashboard-prototype` -->

### Requirement: 原型提供Agent应用平台静态Shell
系统 SHALL 将现有通用模板替换为中文“Agent应用平台”Shell，并展示总览、业务应用、Agent配置、MCP工具、运行中心和系统管理的目标导航；除总览外的未实现模块 MUST 明确标记为规划中或不可操作。
#### Scenario: 查看平台原型导航
- **WHEN** 用户打开前端根页面
- **THEN** 页面展示Agent应用平台品牌、分组侧栏和总览内容
- **AND** 不展示Acme、Revenue、Visitors、Documents、Projects等模板术语
#### Scenario: 查看未实现模块
- **WHEN** 用户查看业务应用之外的规划菜单或动作
- **THEN** 页面以规划中、禁用或说明文本表达尚未实现
- **AND** 不导航到空白业务页面或伪造成功反馈

### Requirement: Dashboard明确区分原型数据与真实运行数据
系统 MUST 在页面全局和使用示例指标的区域标记“原型数据”或等效说明，所有人员、标识、数量、时间和运行记录 SHALL 使用非敏感虚构数据。
#### Scenario: 查看概览指标
- **WHEN** 用户查看业务应用、Agent Profile、MCP Tool和示例运行指标
- **THEN** 页面明确说明指标为静态原型
- **AND** 不暗示这些数字来自后端、数据库或实时监控

### Requirement: Dashboard展示目标控制面全景
系统 SHALL 在单一Dashboard中展示平台概览、代表性业务应用、完整调用链、Workflow预览、MCP Tool预览、示例运行记录、安全边界、外部身份关系和建设状态。
#### Scenario: 评审一次请求的目标链路
- **WHEN** 用户查看平台调用链区域
- **THEN** 页面按Channel、Business Application、Workflow、Agent Runtime、`tool-mcp`、Published Resource Revision和Delivery的顺序展示关系
- **AND** 能区分Agent Runtime、标准MCP传输和只读资源适配器的职责
#### Scenario: 评审系统建设状态
- **WHEN** 用户查看建设状态区域
- **THEN** 页面区分概念原型、后端已有基础、需要适配和尚未实现的能力
- **AND** 不把静态展示标记为已交付业务功能

### Requirement: 原型不得执行真实业务或网络行为
系统 MUST NOT 在原型加载或交互时调用后端API、读取数据库、建立流式连接或提交业务命令；创建、保存、绑定、测试、发布和回滚类动作 MUST 不可执行。

#### Scenario: 加载原型页面
- **WHEN** 页面首次加载并完成渲染
- **THEN** 不产生fetch、XHR、WebSocket或EventSource请求
- **AND** 页面数据仅来自本地静态fixture

#### Scenario: 查看业务动作
- **WHEN** 用户定位到创建应用、编辑流程、测试能力、绑定身份或发布等动作
- **THEN** 对应控件不可执行并提供不可用原因
- **AND** 不显示模拟保存成功、发布成功或测试成功的Toast

### Requirement: 原型支持桌面和窄屏评审
系统 SHALL 在桌面和窄屏下保持导航、卡片、调用链、表格和身份关系可读，状态信息 MUST 不只依赖颜色表达。

#### Scenario: 窄屏查看Dashboard
- **WHEN** 用户在移动端宽度查看原型
- **THEN** 侧栏可收起且内容按单列或纵向流程排列
- **AND** 不出现阻止阅读的横向页面溢出

#### Scenario: 使用辅助技术识别状态
- **WHEN** 用户通过键盘或辅助技术浏览原型
- **THEN** 导航、状态、禁用动作和图标具有可理解的文本或无障碍名称
- **AND** 原型状态可由文字、Badge或图标共同识别


<!-- Reconciled from mcp_new capability: `agent-profile-model-connection-management` -->

### Requirement: Web必须提供默认Agent Profile管理入口
系统 SHALL 在管理 Web 增加“Agent 配置 / Agent Profile”菜单、Profile 列表、创建入口和详情页，并 MUST 使用真实管理 API 展示草稿、当前 Publication、Effective Config、校验结果和 Publication 历史。具备 Agent 全局编辑权限的管理员 SHALL 能够创建 Agent；系统 MUST NOT 提供删除、复制或修改既有 Agent code 与 Runtime kind 的动作。
#### Scenario: 管理员打开Agent Profile列表
- **WHEN** 具备 Agent 读取权限的管理员打开 Agent Profile 菜单
- **THEN** 页面从后端加载 Agent 定义、当前 Publication、Runtime kind 和管理权限
- **AND** 每个 Agent 按当前用户权限显示可编辑或只读状态
#### Scenario: 管理员尝试修改非默认Agent
- **WHEN** 管理员打开非 `default-diagnostic-agent` 的详情
- **THEN** 页面不展示可提交的保存、发布或回滚动作
- **AND** 后端继续拒绝该 Agent 的写请求
#### Scenario: Agent列表为空
- **WHEN** 后端返回空 Agent 列表
- **THEN** 页面展示明确空状态而不是空白网格
- **AND** 具备 Agent 全局编辑权限的管理员可以从空状态打开新建表单
#### Scenario: 管理员打开新建Agent表单
- **WHEN** 具备 Agent 全局编辑权限的管理员点击“新建 Agent”
- **THEN** 页面允许填写 code、名称、说明和项目编码，Runtime固定为`python-v1`
- **AND** 页面明确提示 code 创建后不可修改且创建不会自动发布
#### Scenario: 无编辑权限的用户查看列表
- **WHEN** 仅具备 Agent 读取权限的用户打开 Agent Profile 列表
- **THEN** 页面不提供可提交的新建动作
- **AND** 后端继续拒绝该用户直接提交的创建请求

### Requirement: Agent Profile必须管理限定的Anthropic-compatible模型配置
系统 SHALL 允许默认 Agent Profile 配置一个 `anthropic_compatible` 模型连接，并 SHALL 以规范化字段管理 Base URL、主模型、Opus/Sonnet/Haiku 默认模型、Subagent 模型和 effort level。系统 MUST 将一个 API Key Credential 同时映射为运行时所需的 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN`，MUST NOT 要求用户重复保存相同密钥。

#### Scenario: 配置DeepSeek Anthropic-compatible连接
- **WHEN** 管理员配置 HTTPS Anthropic Base URL、`deepseek-v4-flash` 主模型、默认模型映射、Subagent 模型和 `max` effort
- **THEN** 草稿保存规范化模型连接引用和模型策略
- **AND** Effective Config 能展示非敏感字段及 Key 已配置状态

#### Scenario: 默认模型映射留空
- **WHEN** 管理员只填写主模型并将 Opus、Sonnet、Haiku 或 Subagent 映射留空
- **THEN** 系统在校验和发布时确定性使用主模型补齐空映射
- **AND** Publication 保存补齐后的显式有效值

#### Scenario: 尝试配置不支持的协议
- **WHEN** 请求提交 OpenAI-compatible、任意 HTTP Runtime 或其他未支持 Provider
- **THEN** 系统以字段级错误拒绝保存或发布
- **AND** 不创建新的 Runtime Adapter 或模型连接

### Requirement: 模型API Key必须通过加密Secret管理
系统 MUST 使用现有 encrypted DB Secret Provider 加密保存模型 API Key，API Key 明文 MUST 只在创建或轮换请求中进入服务端，并 MUST NOT 出现在 Agent 草稿、Agent Publication、模型连接查询、日志、审计、错误响应、前端状态或 Agent prompt。页面 SHALL 只展示 configured 状态、脱敏摘要、版本和更新时间。

#### Scenario: 管理员首次保存API Key
- **WHEN** 具备 Secret 管理权限的管理员提交新的模型 API Key
- **THEN** 系统加密保存该值并把稳定 Credential 绑定到模型连接
- **AND** 响应不包含明文、可还原密文或可复制的 Secret URI

#### Scenario: 普通Agent编辑者查看模型连接
- **WHEN** 具有 Agent 编辑权限但不具有 Secret 管理权限的用户打开 Agent Profile
- **THEN** 页面只显示 Key 是否已配置及脱敏状态
- **AND** 用户不能读取、创建、替换、轮换或禁用 Key

#### Scenario: 轮换已暴露Key
- **WHEN** Secret 管理员为同一 Credential 提交新 Key
- **THEN** 系统创建新的 active Secret 版本并停用旧版本
- **AND** 既有 Agent Publication 无需改变即可在后续 attempt 使用新版本

### Requirement: Agent Publication必须固定非敏感模型连接版本
系统 MUST 在发布 Agent Profile 时加载并校验所选模型连接 revision，把连接 ID、revision、config hash、协议、Base URL、有效模型映射和 effort 固定到不可变 Agent Publication，同时只保存稳定 Credential 绑定标识而不保存 Key 明文。新 Agent Publication MUST 不受后续模型 URL、模型映射或 effort 编辑影响。

#### Scenario: 发布合法Agent草稿
- **WHEN** Agent 草稿引用已启用、已配置 Key 且通过连接校验的模型连接 revision
- **THEN** 系统创建包含完整非敏感模型连接快照和 config hash 的 Agent Publication
- **AND** Effective Config 显示该 Publication 的模型连接来源

#### Scenario: 发布后修改模型URL
- **WHEN** 管理员在 Agent Publication 创建后修改模型 Base URL
- **THEN** 现有 Publication 保持原 URL、revision 和 hash
- **AND** 只有重新保存并发布的新 Agent Publication 使用新 URL

#### Scenario: 模型连接缺少Key
- **WHEN** Agent 草稿引用的模型连接没有启用的 active Credential
- **THEN** 校验和发布失败关闭并返回安全字段错误
- **AND** 响应不披露 Credential ID、Secret ref 或内部解密错误

### Requirement: Agent Profile发布不得自动切换业务应用
系统 MUST 保持 Business Application Publication 对 Agent Publication 的不可变引用。发布或回滚 Agent Profile MUST NOT 自动修改任何 Business Application revision、Publication、Deployment 或运行路由；管理 Web SHALL 显示引用当前和历史 Agent Publication 的业务应用，并为仍引用旧版本的应用提供明确提示。

#### Scenario: 默认应用仍引用旧Publication
- **WHEN** 管理员发布新的 Agent Publication，而已激活默认诊断应用仍引用旧 Agent Publication
- **THEN** 当前钉钉路由继续使用旧 Agent Publication
- **AND** Agent Profile 页面显示受影响应用及“需要在业务应用中显式发布并激活”的提示

#### Scenario: 回滚Agent当前Publication
- **WHEN** 管理员把 Agent 当前指针回滚到历史 Publication
- **THEN** 未经 Business Application 路由创建的后续 Job 使用回滚版本
- **AND** 已发布业务应用及已入队 Job 保持各自固定版本

### Requirement: 模型连接测试必须使用真实受限Runtime并防止SSRF
系统 SHALL 提供模型连接测试动作，测试 MUST 使用保存后的模型连接和 active Secret，通过独立 Python Runtime 的官方 Claude Agent SDK 路径执行无工具、单轮、短超时探测。Python API MUST 先执行 RBAC、HTTPS、Provider host allowlist、userinfo、fragment、重定向、回环、链路本地和私网目标校验；Runtime MUST 再按固定 revision/config hash 解析连接。响应 MUST 只包含 Provider Host、模型、Runtime/SDK 版本、耗时和安全结果，不得包含 Key、Secret ref、Prompt、模型响应正文或内部异常详情。

#### Scenario: 测试已保存DeepSeek连接
- **WHEN** Secret 管理员测试已保存、host 被允许且 revision/config hash 固定的 DeepSeek Anthropic-compatible 连接
- **THEN** Python 服务把受限 probe 委托给 `python-agent-runtime`，Runtime 使用 active Key 完成无 Tool 探测并返回安全状态和耗时

#### Scenario: 测试未批准URL
- **WHEN** 管理员提交回环、私网、HTTP、带 userinfo 或 host 不在 allowlist 的 Base URL
- **THEN** Python 服务在调用 Runtime 前拒绝连接
- **AND** 审计只记录脱敏 host、actor、结果和 correlation ID

#### Scenario: 连接版本发生漂移
- **WHEN** Runtime 读取到的模型连接 revision 或 config hash 与 probe 请求不一致
- **THEN** Runtime 在调用 Provider 前失败关闭并返回稳定配置漂移错误

### Requirement: Agent Profile模型连接操作必须授权和审计
系统 SHALL 复用统一 RBAC：读取 Profile 需要 Agent read/edit 权限，创建 Agent 需要 `agent:*:edit` 全局权限，保存草稿需要目标 Agent edit 权限，发布和回滚需要目标 Agent publish 权限，创建或轮换 Key 及执行真实连接测试需要 Secret 管理权限。所有写操作和连接测试 MUST 记录不含敏感值的审计事件。
#### Scenario: 无Secret权限的用户更新Key
- **WHEN** 仅具有 Agent edit 权限的用户提交 Key 创建、轮换或连接测试请求
- **THEN** 系统拒绝请求且不访问外部模型服务
#### Scenario: 发布审计
- **WHEN** 管理员发布包含模型连接的 Agent Publication
- **THEN** 审计记录 Agent code、Publication ID、模型连接 revision、config hash、模型和脱敏 Provider Host
- **AND** 审计不包含 Key、Secret ref、Prompt 或模型响应
#### Scenario: 无全局编辑权限的用户创建Agent
- **WHEN** 用户具备某个既有 Agent 的编辑权限但不具备 `agent:*:edit` 全局权限并提交创建请求
- **THEN** 系统拒绝请求且不写入 Agent Definition 或 Draft
- **AND** 权限拒绝通过统一 RBAC 审计记录
#### Scenario: 创建Agent审计
- **WHEN** 管理员成功创建 Agent
- **THEN** 审计记录 actor、Agent code、Runtime kind、项目编码和初始 Draft revision
- **AND** 审计不包含模型凭据、Secret、Prompt 或业务消息

### Requirement: Agent workflow templates are persisted
系统 SHALL 在 PostgreSQL 中持久化 Agent 诊断流程模板，并 MUST 支持草稿、已发布、禁用等状态。

#### Scenario: Create diagnostic workflow template
- **WHEN** 管理端创建一个订单诊断流程模板
- **THEN** 系统保存模板编码、名称、项目编码、状态、版本、入口节点和扩展设置

#### Scenario: Disable workflow template
- **WHEN** 管理端禁用一个流程模板
- **THEN** 后续运行时选择流程模板时 MUST 不使用该禁用模板

### Requirement: Workflow nodes and edges support drag-and-drop graph editing
系统 SHALL 持久化流程节点、节点位置、节点配置、边、端口和条件配置，以支持后续 Web 拖拽编排。

#### Scenario: Add tool call node
- **WHEN** 管理端在画布中添加一个 Loki 查询节点
- **THEN** 系统保存节点 key、节点类型、标题、画布位置和只读工具调用配置

#### Scenario: Connect two nodes
- **WHEN** 管理端把上下文检索节点连接到工具调用节点
- **THEN** 系统保存边 key、源节点、目标节点、端口和条件配置

### Requirement: Workflow graph is validated before save and publish
系统 SHALL 校验 workflow graph 的结构，至少包括入口节点存在、边引用的节点存在、节点 key 唯一、边 key 唯一和 MVP 只读工具边界。

#### Scenario: Edge references missing node
- **WHEN** 管理端保存一条指向不存在节点的边
- **THEN** 系统拒绝保存并返回图校验错误

#### Scenario: Workflow contains mutation node
- **WHEN** 管理端保存包含写库、删 Redis、重启服务或改代码动作的节点
- **THEN** 系统拒绝保存，因为第一版 workflow 只允许只读诊断流程

### Requirement: Workflow publication creates immutable snapshots
系统 SHALL 在发布流程模板时创建不可变发布快照，运行时后续 MUST 读取发布快照而不是读取正在编辑的草稿图。

#### Scenario: Publish workflow template
- **WHEN** 管理端发布一个合法流程模板
- **THEN** 系统创建新版本发布快照，保存完整 graph snapshot、配置 hash、发布人和发布时间

#### Scenario: Edit draft after publish
- **WHEN** 管理端在发布后继续编辑草稿节点
- **THEN** 已发布快照 MUST 保持不变，直到下一次发布生成新版本

### Requirement: Workflow templates remain configuration until explicitly wired to runtime
系统 SHALL 把 workflow 模板作为配置资产管理，第一版 MUST NOT 因保存或发布模板而自动改变 Agent job 执行链路。

#### Scenario: Save workflow template
- **WHEN** 管理端保存或发布流程模板
- **THEN** 系统只更新配置表和发布快照，不立即启动 Agent job 或执行工具调用


<!-- Reconciled from mcp_new capability: `deepseek-model-connection-setup` -->

### Requirement: 管理Web必须提供连续的DeepSeek模型连接配置向导
系统 SHALL 在默认 Agent Profile 的“模型与连接”区域提供单一连续向导，依次完成 DeepSeek Anthropic Base URL 与 Credential 输入、模型发现、模型映射、真实配置测试和最终保存。系统 MUST NOT 再要求管理员通过独立的连接 revision 保存、Credential 弹窗和已保存版本测试完成一次配置。

#### Scenario: 首次配置模型连接
- **WHEN** 具有 Agent 编辑与 Secret 管理权限的管理员打开尚未配置 Credential 的默认模型连接
- **THEN** 页面按 URL 与 Key、模型发现、模型映射、配置测试和最终保存的顺序引导操作
- **AND** 在最终保存成功前不把连接显示为 ready

#### Scenario: 输入变化使下游结果失效
- **WHEN** 管理员在模型发现后修改 Base URL 或 Credential，或者在配置测试后修改任一模型映射或 effort
- **THEN** 页面清除所有受影响的发现或测试结果
- **AND** 管理员必须从相应步骤重新检测

### Requirement: 系统必须只发现DeepSeek官方服务的模型
系统 SHALL 只接受满足部署 allowlist 的 DeepSeek 官方 HTTPS Anthropic Base URL，并 MUST 通过移除末尾 `/anthropic`、追加 `/models` 确定性派生模型发现 URL。系统 MUST 拒绝 userinfo、query、fragment、非 443 端口、未批准 host、非法 path、redirect，以及解析到回环、链路本地、私网或保留 IP 的目标。

#### Scenario: 从官方Anthropic URL发现模型
- **WHEN** 管理员提交 `https://api.deepseek.com/anthropic` 和有效 Credential
- **THEN** 系统请求同一官方服务的 `https://api.deepseek.com/models`
- **AND** 返回去重、受限且不含 Credential 的模型 ID 列表

#### Scenario: 拒绝第三方或自定义发现地址
- **WHEN** 管理员提交第三方 Anthropic-compatible host、自定义模型列表 URL 或不符合规则的 Base URL
- **THEN** 系统在外部请求前以稳定字段错误拒绝
- **AND** 不尝试猜测第三方 `/models` 路径

#### Scenario: 模型列表响应不安全
- **WHEN** DeepSeek 模型列表为空、格式错误、超出响应大小或模型数量上限
- **THEN** 系统返回稳定安全的模型发现错误
- **AND** 不返回上游响应正文或内部解析异常

### Requirement: 模型发现和草稿测试必须无持久化副作用
系统 SHALL 允许使用本次提交的 API Key 或当前有效 encrypted DB Credential 执行模型发现与草稿配置测试。发现和测试动作 MUST NOT 创建或更新 Secret、Secret version、模型连接 revision、Agent 草稿或 Publication，且 MUST NOT 把 API Key 写入日志、审计 payload、查询缓存或响应。

#### Scenario: 使用新Key发现失败
- **WHEN** 管理员提交新 API Key 但 DeepSeek 拒绝鉴权或请求超时
- **THEN** 系统返回脱敏错误并保持数据库不变
- **AND** 不创建孤立 Secret 或 rotation-required revision

#### Scenario: 沿用已有Credential执行发现
- **WHEN** 当前模型连接绑定可用 Credential 且管理员选择沿用
- **THEN** 服务端内部解析 active Secret 完成发现
- **AND** 前端仍只看到 configured 状态、脱敏摘要和模型列表

#### Scenario: 关闭向导清除明文
- **WHEN** 管理员关闭、离开或成功完成配置向导
- **THEN** 前端立即清空 API Key input state 和 mutation variables
- **AND** 不把该值写入 URL、local storage、session storage 或 TanStack Query data

### Requirement: 模型映射必须由当前发现结果驱动
系统 SHALL 要求主模型选择自当前发现结果，并 SHALL 允许 Opus、Sonnet、Haiku 和 Subagent 映射选择发现模型或继承主模型。最终保存前系统 MUST 把继承项规范化为显式主模型，并 MUST 重新确认所有模型仍在最新发现列表中。

#### Scenario: 配置不同模型映射
- **WHEN** 管理员从发现列表分别选择主模型、Opus、Sonnet、Haiku 和 Subagent 模型
- **THEN** 页面显示每个映射的明确选择
- **AND** 草稿测试与最终连接 revision 使用同一组规范化模型

#### Scenario: 默认映射继承主模型
- **WHEN** 管理员把任一默认模型或 Subagent 模型设为“继承主模型”
- **THEN** 系统在测试和保存前使用主模型补齐
- **AND** 保存的非敏感 config 包含补齐后的显式值

#### Scenario: 旧模型不再可用
- **WHEN** 当前历史 revision 的模型不在最新发现列表中
- **THEN** 页面显示旧值和不可用警告但不修改历史 revision
- **AND** 管理员必须重新选择可用模型后才能保存新 revision

### Requirement: 保存前必须通过真实Claude Agent SDK配置测试
系统 SHALL 使用临时非敏感配置和本次 Credential 来源，通过与生产 Job 相同的 Claude Agent SDK 兼容路径执行无 Tool、无 MCP、单轮、短超时测试。测试 MUST 使用所选主模型，MUST NOT 接受任意 Prompt，并 MUST NOT 返回模型响应正文、SDK stderr、Credential 或请求 header。

#### Scenario: 草稿配置测试成功
- **WHEN** 规范化 URL、Credential 和所选主模型可以通过 Claude Agent SDK 完成最小探测
- **THEN** 系统返回 provider host、模型、耗时和成功状态
- **AND** 页面允许进入最终保存步骤

#### Scenario: 发现成功但模型调用失败
- **WHEN** `/models` 返回所选模型但 Claude Agent SDK 认证、模型调用或协议兼容测试失败
- **THEN** 系统返回稳定安全错误并禁止最终保存
- **AND** 数据库与 active Secret 保持不变

### Requirement: 最终配置必须原子保存Secret和连接revision
系统 SHALL 提供一个带 `expected_revision` 的原子配置动作。该动作 MUST 在数据库事务外重新执行模型发现与真实配置测试，在提交前再次校验 revision，并 MUST 在同一数据库 unit of work 中创建或轮换 encrypted DB Secret、追加一个 ready 模型连接 revision、更新 current revision/status 和写入脱敏审计。任一步失败时 MUST 不产生部分写入。

#### Scenario: 首次原子配置成功
- **WHEN** 未绑定 Credential 的连接提交有效 URL、API Key、模型映射和当前 expected revision
- **THEN** 系统创建 encrypted DB Secret 并追加绑定该 Secret 的 ready revision
- **AND** 响应只返回公共连接状态和脱敏 Credential 摘要

#### Scenario: 最终验证失败
- **WHEN** 最终保存时重新发现的模型列表不再包含所选模型或 SDK 测试失败
- **THEN** 系统不创建 Secret、Secret version 或连接 revision
- **AND** 当前连接状态和 revision 保持不变

#### Scenario: 保存期间发生并发修改
- **WHEN** 外部测试完成后连接 revision 已不再等于 expected revision
- **THEN** 系统返回包含当前 revision 的 409
- **AND** Secret 与连接 revision 均不发生部分更新

### Requirement: 原子配置必须支持Credential沿用、轮换和缺失恢复
系统 SHALL 允许新 revision 沿用当前可用 Credential，或在管理员提交新 API Key 时轮换同一受管 Credential。当前绑定缺失、停用、不可解析或处于 rotation-required 状态时，系统 MUST 要求新 API Key。确定性 Secret code 已存在但未绑定时，系统 MUST 仅在其所有权 metadata 明确属于同一 model connection 时允许轮换并重新绑定。

#### Scenario: 沿用当前有效Credential
- **WHEN** 管理员只修改模型映射并选择沿用当前有效 Credential
- **THEN** 新 revision 继续绑定同一 Secret 身份
- **AND** 系统不创建新的 Secret version

#### Scenario: 轮换当前Credential
- **WHEN** 管理员提交新的 API Key 并完成最终配置
- **THEN** 系统创建新的 active Secret version并让新 revision 保持稳定 Credential 身份
- **AND** 旧明文和旧 active version不再解析

#### Scenario: 恢复未绑定连接
- **WHEN** 当前连接为 rotation-required 且没有 Secret 绑定，管理员提交新 API Key
- **THEN** 系统创建或安全重新绑定属于该连接的受管 Secret
- **AND** 连接在同一事务中进入 ready

#### Scenario: 拒绝Secret所有权冲突
- **WHEN** 确定性 Secret code 已由其他资源或其他 model connection 管理
- **THEN** 系统失败关闭并返回 Credential 所有权冲突
- **AND** 不轮换、不覆盖且不重新绑定该 Secret

### Requirement: 模型连接配置操作必须授权、限流、审计和脱敏
系统 SHALL 要求 Agent 编辑权限与 Secret 管理权限才能执行 discover、test-draft 和 configure，并 MUST 对外部探测动作实施用户与连接维度限流。系统 MUST 使用稳定中文错误区分 URL、鉴权、发现、空模型、模型不可用、SDK 测试、超时、并发和所有权冲突；审计和运行输出 MUST 不包含 API Key、Authorization header、Secret ref、模型响应正文或完整上游错误。

#### Scenario: 无Secret权限执行模型发现
- **WHEN** 只有 Agent 编辑权限的用户提交 discover、test-draft 或 configure
- **THEN** 系统在任何 Secret 解析或外部网络请求前拒绝
- **AND** 不产生模型调用费用或配置写入

#### Scenario: 探测请求超过限额
- **WHEN** 同一用户或连接在限流窗口内超过允许的发现或测试次数
- **THEN** 系统返回稳定限流错误且不访问 DeepSeek
- **AND** 审计只记录 actor、连接 code、动作和安全结果

#### Scenario: 安全错误投影
- **WHEN** DeepSeek 或 Claude Agent SDK 返回包含请求 header、Key、响应正文或内部异常的失败
- **THEN** API 只返回稳定错误码和中文安全摘要
- **AND** 日志、审计和前端状态不包含敏感原文


<!-- Reconciled from mcp_new capability: `multi-agent-configuration` -->

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 在 deployment bootstrap 中仅幂等初始化固定 `python-v1` 的默认诊断 Agent，并 SHALL 只允许受权管理员创建 `python-v1` 业务 Agent。退役前已经持久化的 `typescript-v1` Definition、Publication、终态 Job 和审计事实 MUST 保留原始 runtime kind 并只读展示；系统不得新建、编辑、发布、回滚或执行 TypeScript Agent，也不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 默认Python Agent初始化
- **WHEN** 系统完成 migration 和 Agent bootstrap
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 系统不创建 `typescript-diagnostic-agent` 或其它 `typescript-v1` Agent

#### Scenario: 创建Python Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `python-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `python-v1`

#### Scenario: 旧客户端创建TypeScript Agent
- **WHEN** 旧客户端提交 `typescript-v1` 或其它非 `python-v1` runtime kind
- **THEN** 系统拒绝请求且不创建 Definition 或 Draft

#### Scenario: 读取历史TypeScript Agent
- **WHEN** 管理员查看退役前已存在的 `typescript-v1` Agent
- **THEN** API 返回其原始只读 Definition、Publication 和 runtime 标签
- **AND** 不允许编辑、发布、回滚为当前版本或用于新执行

#### Scenario: 重复运行Agent bootstrap
- **WHEN** 已存在固定 Agent、用户 Draft 或 Publication 后再次运行 Agent bootstrap
- **THEN** 系统不覆盖既有名称、配置、版本、Publication 或业务应用引用
- **AND** 固定 code 对应的 runtime kind 不一致时 bootstrap 失败关闭

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Python Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、不可变 `python-v1` runtime kind、schema version 和 config hash 的不可变 publication snapshot。草稿不得覆盖 Definition 的 runtime kind；历史 TypeScript snapshot 只可读取，不得作为新草稿或 Publication 的种子。

#### Scenario: 编辑已发布Python Agent草稿
- **WHEN** 管理员修改已发布 Python Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新该 Agent 的新草稿 revision，现有 publication 与 runtime kind 保持不变

#### Scenario: 发布合法Python草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Python Agent 草稿
- **THEN** 系统创建包含 `python-v1` 的新不可变 publication，并更新该 Agent 的当前发布指针

#### Scenario: 草稿伪造Runtime
- **WHEN** 草稿 payload 的 runtime kind 不是 `python-v1` 或与 Agent Definition 不一致
- **THEN** 系统拒绝校验和发布且不创建 publication

#### Scenario: 历史TypeScript Publication生成草稿
- **WHEN** 管理员尝试从历史 `typescript-v1` Publication 创建、发布或回滚草稿
- **THEN** 系统拒绝变更并提示先创建或选择 Python Agent Publication

### Requirement: Agent 发布配置区分可编辑业务层和强制安全层
系统 SHALL 允许草稿配置业务指令、模型策略、执行限制、只读工具、Skill、默认 routing 和 Channel/Delivery 绑定，但 MUST NOT 允许配置覆盖平台安全规则、用户权限、只读工具策略、SDK 写工具禁用或 secret 明文。

#### Scenario: 管理员保存业务指令
- **WHEN** 管理员修改默认 Agent 的诊断目标和报告偏好
- **THEN** 系统把内容保存到业务指令层，并在运行时叠加强制安全层

#### Scenario: 草稿尝试开放写工具
- **WHEN** 草稿包含 Bash、Write、Edit、写数据库、Redis mutation 或未注册 executable tool
- **THEN** 系统拒绝校验和发布

### Requirement: Agent job 固定发布版本
系统 SHALL 在创建 Job 的数据库事务中保存 Agent definition、publication ID、revision、config hash、runtime kind 和 Runtime 协议版本。Worker 和 retry MUST 使用 Job 固定的 publication 与 Runtime，不得重新读取当前发布指针、草稿或迁移门禁，也不得在故障时跨 Runtime fallback。

#### Scenario: 发布后创建Job
- **WHEN** Application 选择的 Agent Publication 有效且用户提交请求
- **THEN** Job 在发布队列前固定该 publication ID、revision、hash、runtime kind 和协议版本

#### Scenario: Job排队期间发布新版本
- **WHEN** Job 已固定版本后管理员发布新的 Agent revision
- **THEN** 已排队 Job 继续使用原版本和 Runtime，新 Job 才使用新 Publication

#### Scenario: Job重试
- **WHEN** Job 因瞬时错误进入 retry
- **THEN** 重试仍使用原 publication snapshot、runtime kind、协议版本和 invocation 规则

#### Scenario: 固定Runtime不可用
- **WHEN** Job 固定的 Runtime 暂时不可连接
- **THEN** Worker 按固定错误分类重试或终止，不自动调用另一 Runtime

### Requirement: Agent 发布支持校验和回滚
系统 SHALL 在发布前校验引用的模型策略、工具、Skill、connector、项目和安全边界，并 MUST 通过切换当前发布指针回滚到历史 publication，不修改历史快照。

#### Scenario: 发布引用禁用工具
- **WHEN** 草稿分配已禁用或非只读工具
- **THEN** 系统拒绝发布并返回字段级校验错误

#### Scenario: 回滚默认 Agent
- **WHEN** 具备发布权限的管理员选择一个历史有效 publication 回滚
- **THEN** 系统把它设为新 job 的当前版本、记录审计，并保持历史 publication 不变

### Requirement: 未发布或无效 Agent 必须 fail closed
系统 SHALL 在目标 Agent 没有启用的有效 publication、publication hash 不一致或 snapshot schema 不受支持时拒绝创建或执行新 job。

#### Scenario: 默认 Agent 尚未发布
- **WHEN** Channel 请求选择默认 Agent但它没有有效 publication
- **THEN** 系统返回安全配置错误且不发布 Agent job

### Requirement: Agent管理界面只管理Python Runtime并只读展示历史TypeScript事实
Agent 管理 API 与前端 SHALL 只允许创建、编辑、校验、发布和回滚 `python-v1` Agent。页面 SHALL 对历史 `typescript-v1` Definition 和 Publication 显示明确的“已退役、只读”状态，不得把历史 runtime kind 映射或显示为 Python。

#### Scenario: 管理员创建并发布Python Agent
- **WHEN** 具备权限的管理员创建 Agent、保存合法草稿并发布
- **THEN** 页面和 API 固定使用 `python-v1`，且不提供 Runtime 选择控件

#### Scenario: 管理员查看历史TypeScript Agent
- **WHEN** 管理员打开退役前的 TypeScript Agent 或 Publication
- **THEN** 页面显示原始 `typescript-v1`、历史 revision/hash 和只读状态
- **AND** 编辑、发布、回滚为当前版本和新应用选择动作均不可用

#### Scenario: 旧客户端提交TypeScript Runtime
- **WHEN** 旧客户端在创建、草稿、发布或回滚请求中提交 `typescript-v1`
- **THEN** API 失败关闭并返回稳定迁移提示，不静默改写为 Python

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/agent-model` -->

### Requirement: Workflow 草稿图必须只有一个可变事实源
系统 SHALL 将 `agent_workflow_node` 与 `agent_workflow_edge` 的规范化记录作为 Workflow 草稿图的唯一可变事实源；完成兼容切换后，模板记录中的 `graph_json` MUST NOT 参与草稿读取、校验、hash 或发布，也 MUST NOT 继续双写。

#### Scenario: 编辑草稿节点和连线
- **WHEN** 管理端新增、移动、修改或删除 Workflow 节点或边
- **THEN** 系统只更新规范化 node/edge 记录及必要的模板元数据
- **AND** 草稿重新读取后与本次编辑完全一致

#### Scenario: 兼容图副本与规范化记录不一致
- **WHEN** contract 前核对发现模板 `graph_json` 与规范化 node/edge 记录不等价
- **THEN** 迁移失败关闭并输出不含业务配置正文的差异摘要
- **AND** 系统不得根据时间戳或非确定性规则静默选择其中一份覆盖另一份

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/agent-model` -->

### Requirement: Workflow 发布快照必须从规范化草稿原子生成
系统 MUST 在一个一致的数据库读取边界内，从模板元数据和规范化 node/edge 草稿生成确定性 graph snapshot、schema version 与 config hash，并 SHALL 将该 snapshot 保存为不可变的已发布运行事实。发布后编辑草稿不得改变历史 snapshot。

#### Scenario: 发布规范化 Workflow 草稿
- **WHEN** 管理端发布通过校验的 Workflow 草稿
- **THEN** 系统从规范化 node/edge 记录生成一个确定排序的不可变 snapshot 和 hash
- **AND** Runtime 后续只读取固定 publication snapshot

#### Scenario: 发布期间草稿并发变化
- **WHEN** 生成 publication snapshot 时草稿 revision 已被并发更新
- **THEN** 系统拒绝本次发布或基于同一已锁定 revision 完整发布
- **AND** 不得产生混合两个 revision 的 snapshot

<!-- Integrated from archived change: `2026-08-23-add-agent-profile-creation/specs/agent-model` -->

### Requirement: Agent创建必须原子生成初始草稿
系统 MUST 在同一数据库事务中创建 `python-v1` Agent Definition 与 r1 Draft。初始 Draft SHALL 使用平台固定的非敏感默认配置和所选项目范围，MUST NOT 接受客户端指定 Publication、状态、classification、created_by、任意模型凭据或 Runtime 覆盖，并 MUST NOT 自动发布或改变运行路由。

#### Scenario: 成功创建Agent
- **WHEN** 受权管理员提交合法、唯一且 runtime kind 为 `python-v1` 的 Agent 创建请求
- **THEN** 系统原子创建 Definition 和归属该 Definition 的 r1 Draft
- **AND** `current_publication_id` 为空且不存在因本次创建产生的业务应用引用

#### Scenario: Agent code重复
- **WHEN** 两个请求串行或并发提交同一 Agent code
- **THEN** 至多一个请求创建 Definition 与 r1 Draft
- **AND** 其他请求返回稳定 `agent_code_conflict`，不产生孤立 Definition 或 Draft

#### Scenario: 创建请求包含平台控制字段
- **WHEN** 客户端提交 status、classification、current publication、created_by、Draft config 或其他未声明字段
- **THEN** API 拒绝请求且不写入任何 Agent 记录

#### Scenario: 创建请求使用非法Runtime
- **WHEN** 客户端提交 `typescript-v1` 或其它非 `python-v1` runtime kind
- **THEN** API 返回字段级校验错误且不创建 Definition 或 Draft

<!-- Integrated from archived change: `2026-08-23-harden-management-and-runtime-boundaries/specs/agent-model` -->

### Requirement: Workflow 管理必须使用 Agent 权限矩阵
系统 SHALL 将 Workflow 模板、节点、边和发布记录视为 Agent 管理资产。读取 MUST 要求 `agent/read`，草稿新增、修改、启停 MUST 要求 `agent/edit`，发布 MUST 要求 `agent/publish`；Workflow API MUST NOT 复用平台配置 manage 作为通用管理员权限。

#### Scenario: 只有 Agent 读取权限
- **WHEN** 已登录用户只有 `agents.read`
- **THEN** 用户可以读取 Workflow 模板、节点、边和最新 Publication，但修改和发布返回 403

#### Scenario: 具有 Agent 编辑权限
- **WHEN** 已登录用户具有 `agents.edit` 但没有 `agents.publish`
- **THEN** 用户可以保存草稿和修改图，但发布返回 403

#### Scenario: 具有 Agent 发布权限
- **WHEN** 已登录用户具有 `agents.publish` 且发布内容通过校验
- **THEN** 系统创建不可变 Workflow Publication 并记录当前 principal actor
