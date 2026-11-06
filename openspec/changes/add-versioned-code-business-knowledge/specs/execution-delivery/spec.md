## ADDED Requirements

### Requirement: 受管代码提取必须复用标准 Job 与 Runtime 边界
系统 SHALL 提供受信的内部代码知识构建入口，使用已启用的受限服务账号、明确发布的提取 Agent/Application、Session/Execution Policy 和标准 Job 创建事务，固定来源快照、允许范围、构建/工作单元及配置关联，并创建唯一 dispatch Outbox。Worker SHALL 继续拥有 Job 生命周期和恢复，模型执行只在既有 Python Runtime 内发生；调度器和 Worker MUST NOT 内嵌 SDK、模型凭据或任意执行程序。内部提取 Job SHALL 使用内部结果路由，不生成外部聊天、钉钉或 Webhook 消息交付；此路由不改变普通业务 Job 的交付合同。

#### Scenario: 每日计划触发提取
- **WHEN** 已核验来源出现需要分析的变化且提取配置已发布
- **THEN** 创建具备完整 provenance 的内部 Job，运行中心可追溯来源、模型配置和构建身份，外部渠道不收到提取产物

#### Scenario: 提取 Agent 未发布或账号失效
- **WHEN** 计划尝试创建任务但发布或当前身份授权不满足
- **THEN** 任务停在明确的配置/授权失败状态，不调用临时模型或默认诊断 Agent 绕过限制

### Requirement: 提取工作单元必须固定来源授权且有界执行
一个提取 Job MUST 绑定不可变源码快照、允许路径/业务范围、提取合同、Agent/模型/Skill 配置和受限产物工作区；Runtime 从服务端 Job 关联核实源码挂载授权，不信任模型传入的 build_id 或路径。大型构建 SHALL 拆分为持久工作单元，每个单元遵循既有 Job 截止、Runtime 池准入、工具调用预算及 Runtime 沙盒配额。扩大依赖范围只能由确定性控制器在已批准来源内创建后续单元；模型不得扩大来源或重置预算。

#### Scenario: 仓库文件数超过单 Job 工作集上限
- **WHEN** 提取需要访问大量源码
- **THEN** 使用固定快照的只读来源挂载和分批工作单元，不把整个仓库物化到单个沙盒或提升全局配额

#### Scenario: 执行期间来源配置改变
- **WHEN** 管理员修改仓库、分支、范围或提取配置
- **THEN** 已冻结任务不读取新配置混合执行；当前授权或来源范围失效时拒绝后续读取，调度器以新配置创建新构建

#### Scenario: 必要依赖超出批准范围
- **WHEN** Agent 发现无法在当前授权内读取的关联实现
- **THEN** 输出未解析依赖，控制器仅按既有批准边界处理，不自动授予来源外权限

### Requirement: 提取产物与知识激活必须分开且可恢复
Agent SHALL 在本 Job 限定输出目录写入候选知识包及报告；Runtime SHALL 在沙盒清理前回收到独立持久产物卷，原子提交清单 MUST 固定确切 Job/Invocation、build/unit、source_snapshot、request/config 摘要及文件内容摘要和大小。代码知识流程 MUST NOT 使用 File Service、伪造聊天附件或接受模型指定宿主产物路径。Worker MUST 从服务端验证产物归属及合同后推进校验/索引；不得因模型最终回答声称成功或提供任意文件路径而激活知识。Job/Invocation 重放 SHALL 复用已有结果，未知执行结果按现有恢复合同处理，不以自动重试重复运行尚不能证明停止的 Agent。阶段推进及候选成员更新 MUST 校验构建租约版本和固定配置。

#### Scenario: Agent 成功而索引失败
- **WHEN** 候选包已保存但后续 Qdrant 写入失败
- **THEN** 重试从已验证候选继续，不再次提取未变化内容，旧可用快照保持服务

#### Scenario: Runtime 完成而 Worker 提交失败
- **WHEN** Runtime 有可靠终态但工作单元结果事务尚未提交
- **THEN** 按原 Invocation/digest 恢复并幂等关联产物，不创建第二份模型执行

#### Scenario: 模型声称已发布
- **WHEN** 模型输出包含发布成功文字但没有通过服务端校验的候选包
- **THEN** 构建不进入 READY 或 ACTIVATED，记录产物不满足合同的安全失败

### Requirement: 历史派生构建必须分离请求人和提取执行身份
系统 SHALL 在已授权的版本查询与后台历史构建之间保存有界、幂等的需求关联，分别记录请求人及执行服务身份。查询 Job SHALL 在原截止内返回待处理状态；后台 Job 使用固定的受限提取发布和来源权限，不继承请求人的任意工具，也不向请求人开放源码或管理权限。需求来源权限、执行账号和配置 MUST 在创建/执行时复核；结果读取仍要求请求人当前 KB 授权。按需构建不得自动切换开发或现场版本，重复请求不得突破队列预算。

#### Scenario: 用户等待历史版本期间权限被撤销
- **WHEN** 后台已完成知识构建，但用户 KB 权限已撤销
- **THEN** 用户后续读取被拒绝，不因曾经提出构建需求而获得持续访问权

#### Scenario: 问答 Job 到期而历史任务未完成
- **WHEN** 历史构建超过原问答的剩余预算
- **THEN** 原问答报告持久任务状态并结束等待，后台按自身授权/预算运行，不延长原 Job 或自动对外发送消息

### Requirement: 代码提取审计限定元数据
受管代码提取 SHALL 保留 Job/Invocation、来源绑定、运行状态、模型用量和工具事件元数据；MUST NOT 将 SDK 消息全文、源码读取结果、候选正文或原始模型 API 请求/响应写入普通运行审计。原文 SHALL 只进入受控来源卷、候选产物卷和校验后的知识修订；普通诊断 Job 的既有审计行为不变。

#### Scenario: 提取模型阅读源码并生成候选
- **WHEN** Read 返回源码或 Write 写入候选 JSON
- **THEN** 普通运行审计只保留有界运行元数据，不重复保存源码和候选正文

#### Scenario: SDK 初始化提取会话
- **WHEN** 受管提取收到 SDK system/init 消息
- **THEN** 仅保存有界工具名、原生 Skill 名、MCP 名称/状态及实际 SDK/CLI 版本；缺失或过滤的数据明确为未知/不完整，不以配置推断初始化结果
- **AND** 不保存 init 的其他字段或完整 SDK 消息，普通 Job 审计保持原行为

### Requirement: 代码提取权限检查失败必须阻断调用
Runtime SHALL 对所有提取工具调用注册无 matcher 限制的 PreToolUse 检查，并设置 SDK 支持的 `on_failure="block"`。未授权工具、路径/范围/预算不符或意外授权异常 MUST 返回拒绝；回调抛错或返回非法结果 MUST 阻断调用。不能支持此策略的 SDK/CLI MUST 拒绝启动该会话，不得静默降级。错误反馈 MUST NOT 包含异常正文、源码、候选值或认证材料。

#### Scenario: 来源授权出现意外文件系统异常
- **WHEN** hook 的读取范围或路径校验抛出未预期异常
- **THEN** 工具调用被拒绝，只返回固定安全原因，不进入普通自动批准流程

#### Scenario: SDK 回调结果无效
- **WHEN** 权限 hook 抛错、没有返回结果或返回值被 CLI 拒绝
- **THEN** CLI 按失败阻断策略拒绝该调用，不把检查失败解释为没有意见
