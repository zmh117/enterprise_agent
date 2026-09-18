## ADDED Requirements

### Requirement: 知识工具发布必须限定内网模型全链路
包含知识工具的 Agent Publication SHALL 固定 `internal_only` 模型数据边界，并要求受信部署认可的本地/内网模型连接。认可 MUST 绑定模型连接 revision/config hash、实际路由和允许模型映射，具备不向外部模型转发的部署及出口控制证据；普通编辑者的勾选、私网地址或一次调用成功 MUST NOT 单独作为认可依据。主模型、Opus/Sonnet/Haiku、Subagent、压缩、总结和 fallback 的全部实际模型路径 MUST 满足该边界，未配置映射按现有规则继承主模型。

系统 MUST 复用现有 Anthropic-compatible 协议和内部网关校验，不因知识接入增加任意协议、地址或 Runtime Adapter。边界未验证或任一路径不受控 MUST 阻止知识工具发布；无知识能力且不含受保护上下文的既有 Agent 保持原有模型合同。

#### Scenario: 本地 Embedding 但外部聊天模型
- **WHEN** 知识库使用本地向量化，但 Agent 主模型或某个子 Agent/总结/fallback 映射指向外部模型
- **THEN** 发布拒绝，不能以 Embedding 本地作为正文不外发的充分条件

#### Scenario: 内网网关转发公网模型
- **WHEN** 网关地址在私网，但未获得不向外部转发的受信部署认可
- **THEN** 系统按模型边界未核验拒绝知识工具发布，不由 Agent 编辑者自行覆盖

#### Scenario: 继承默认模型
- **WHEN** 模型别名或 Subagent 配置为空并按当前规则继承主模型
- **THEN** 系统校验规范化后的全部有效映射，并在 Publication 固定它们及数据边界

### Requirement: 内网数据边界必须先于模型请求并传播到会话
知识工具 Job MUST 在首次模型 I/O 前确定 `internal_only`，运行前复核固定模型版本与当前受信部署状态。该 Job 的问题、检索结果、ONES 正文及其摘要/历史/受保护结果引用 MUST 仅进入本地/内网模型，错误重试、压缩、子 Agent 与 fallback 均不得转外部模型。边界 MUST 随 Session、历史摘要及供模型读取的产物传播，不能因下一 Job 移除知识 Tool、切换 Agent、恢复旧 Publication 或复制历史而清除。

无法保持边界时系统 MUST 在模型访问前拒绝，并要求不携带受保护历史或附件的新会话；MUST NOT 静默删除标记后发送上下文。诊断和外部遥测 MUST NOT 携带检索 query、向量、业务正文或受保护摘要；既有受控运行记录的访问/保留要求保持生效。

#### Scenario: 内网模型不可用
- **WHEN** 知识 Job 的内部模型不可用或部署认可被撤销
- **THEN** 当前执行安全失败，不回退外部模型，不把查询或 ONES 内容发送到外部探测服务

#### Scenario: 下次 Job 不再包含知识工具
- **WHEN** 用户恢复已有知识结果的会话并选择外部模型，即使新 Job 未包含知识工具
- **THEN** 系统在首个模型请求前拒绝复用该上下文，保留 internal_only 标记

#### Scenario: 受保护结果被导入另一会话
- **WHEN** 历史摘要或结果产物被后续 Job 引用为模型输入
- **THEN** 接收方必须继承并校验内网边界，不能通过产物或历史复制绕过限制

#### Scenario: 发布或运行回退
- **WHEN** 操作者停用知识工具并回退到旧 Publication 或执行版本
- **THEN** 已含知识数据的会话仍受内网限制；不能执行该限制的旧运行版本不得恢复它
