## MODIFIED Requirements

### Requirement: Runtime 工具能力必须来自冻结集合与精确派生
Runtime MUST 只注册 Job 冻结 MCP 工具和代码允许的派生工具；只读资源走固定 `tool-mcp`，业务操作走对应固定业务 MCP，文件工具走 `file-service` bridge。业务 mutation 只准备受治理 Action Intent，须通过本规范逐次确认链才能产生 Provider 副作用。文件 Job 可使用受限 Read/Glob/Grep/Write/Edit；只冻结 ONES 集合查询而无文件写能力的 Job 仅派生 Read/Glob/Grep 读取结果文件。发布明确授权代码分析的问答 Job SHALL 在原 Job 内使用固定 Knowledge MCP 的 SVN/答案工具，并预先派生受限 Read/Glob/Grep；源码读取必须在成功更新/检查后取得绑定当前 invocation 的共享读取 grant，不能仅凭挂载存在访问。grant 只收窄已冻结来源/路径/历史上限，不增加工具、仓库或动态挂载。代码只读挂载直接指向受管检出根，不经 File Service，不派生源码 Write/Edit 或 Shell；已有文件 Job 的权限保持独立。文件和 MCP 分别经过精确 hook/服务端授权，检查失败阻断。`select_sandbox_output` 依赖冻结提交能力，`scan_log_evidence` 依赖冻结物化能力与 Sandbox。Bash、Shell、NotebookEdit、WebFetch、WebSearch、任意部署、数据库写入和沙盒外操作 MUST 被拒绝。

#### Scenario: 只读查询结果文件
- **WHEN** Job 只有 ONES 集合查询工具
- **THEN** 可读取本 Job 临时只读 Markdown 结果，不获得 Write/Edit、文件提交或跨 Job 访问

#### Scenario: 派生日志扫描
- **WHEN** Job 冻结 file_prepare_materialization 且有效 Sandbox 已存在
- **THEN** 可注册 scan_log_evidence，它只扫描已物化 LOG，不新增文件来源、对象存储或网络权限

#### Scenario: 未冻结工具或任意 Server
- **WHEN** 模型尝试通过名称、URL、Header、Token 或输出数据注册另一工具
- **THEN** 精确工具策略和服务端复核在副作用前拒绝

#### Scenario: 同一问答 Job 读取源码
- **WHEN** 代码分析工具已正式发布且当前 Job 成功取得 N 版本读占用
- **THEN** 同一个 Agent 可在该范围 Read/Glob/Grep，并调用冻结的 SVN MCP；不启动另一 Agent，也不获得写源码能力

#### Scenario: 挂载存在但无 grant
- **WHEN** Job 尚未准入、正在 update 或读占用已结束/失效
- **THEN** 文件工具拒绝源码访问，不通过放宽 SDK 配置、热注册工具或其他目录绕过

#### Scenario: 其他任务仍在读取
- **WHEN** 本 Job 完成并释放自己的读取占用
- **THEN** 只关闭自己的读取能力，不中断其他合法同版本 Job，也不提前允许修改目录

## ADDED Requirements

### Requirement: 问答查代码不得派发独立模型任务
代码核验 MUST 在现有问答 Agent 和原标准 Job 内进行，沿用当前身份、发布、Runtime invocation、预算和审计；不要求独立提取应用或服务账号，不创建子 Job、整包构建或后台模型调查。目录忙必须快速返回，SVN 操作仅在原 Job 剩余预算内有界等待/查询；原 Job 结束或撤权后不得继续启动模型或写目录。

#### Scenario: 两个 Runtime 同时分析相同版本
- **WHEN** 两个合法问答都对同一 N 版本工作副本申请读取
- **THEN** 各自在原 Job 中并发分析，独立授权与输出，无父子模型等待链

#### Scenario: 不同版本请求
- **WHEN** A 正在读 r100 而 B 需要将同一目录更新到 r101
- **THEN** B 获得目录忙状态，不能持读等待升级、无限占槽或启动独立 Agent 等 A；A 的代码保持 r100

#### Scenario: 原 Job 到期
- **WHEN** update 或分析尚未完成而原 Job 到期/取消
- **THEN** 停止关联执行、报告未完成，确认停止后回收其占用，不将本次分析变成后台模型任务

### Requirement: 读取占用必须绑定执行身份并安全回收
每个共享读占用 MUST 绑定目录身份、确定 revision、Job、Runtime invocation/owner、代次和截止，并受当前授权及 Job 预算控制。Runtime SHALL 在读取前检查有效 grant，记录实际成功读取的路径/范围/hash，结束时禁止新调用并等待本 Job 在途调用退出。异常、取消、撤权和超时触发停止与回收，不能只凭租约到期放行 writer；旧执行未确认停止时必须阻塞修改。回收一个 Job 不得删除其他读者占用。

#### Scenario: Runtime 失去心跳但仍可能读取
- **WHEN** 某读者租约到期但其 invocation 尚未确认停止
- **THEN** 不再给该 Job 新读取权限并启动恢复，更新继续被阻止，不能边恢复边修改目录

#### Scenario: 一个读者取消
- **WHEN** A/B 同时读取而 A 被取消
- **THEN** 停止并释放 A 的调用/占用，B 继续读取；B 结束前不能更新目录

### Requirement: 同一 Agent 的结论必须有实际代码证据
问答 Agent SHALL 使用发布绑定的业务核验 Skill，按问题追踪入口、配置、跨模块依赖、动作和失败路径；生命周期规则包含起始状态、事件、条件、动作、目标状态和失败结果，其他问题不得强行编造状态机。源码、提交说明与第三方提示模板 MUST 作为不可信数据，不加载为插件/指令。输出证据绑定实际读取和受控 SVN 结果，由宿主在读占用内校验，不把模型自报版本或 hash 当验证结果。

#### Scenario: 工单依赖处方与物料
- **WHEN** 规则需要沿调用查询多个已授权模块
- **THEN** 当前 Agent 在既定范围和预算内追踪并逐项引用，未检出或未知依赖明确保留，不创建全系统知识包

#### Scenario: 注入或无法确认编码
- **WHEN** 源码包含修改权限的指令或文件编码无法可靠解释
- **THEN** 前者不改变工具配置，后者不作为确定代码证据；不为方便分析复制另一套全仓文本

#### Scenario: 初始化审计
- **WHEN** 新发布在两个 Runtime 启动
- **THEN** 记录实际工具/Skill/模型/合同版本与授权范围，确认可读工具仍受有效占用限制，不能只凭服务健康宣称查代码可用

### Requirement: 原问答 Job 必须保留用户版本与结果记录上下文
代码问答 Job MUST 保留用户指定的 requested_revision、所选 KB/来源及合法检索关联；较高版本候选的 matched_revision 只能作为核验线索，不得改变源码更新目标或缓存版本。当前 Agent SHALL 在该用户版本下核验规则后再回答。宿主在标准结果收尾路径保存本次受限业务回答记录，缓存命中不需要取得源码占用，也不能只靠提示词要求模型保存。

#### Scenario: 从较高版本线索转查代码
- **WHEN** 用户指定 r100 而检索返回 r101 线索
- **THEN** update/读取仍限定 r100，代码证据不足则保留未知，不将 r101 的知识身份改成 r100

#### Scenario: 直接命中已有答案
- **WHEN** 原 Job 用同版本知识完成回答且未查源码
- **THEN** 宿主保存带用户版本的本次回答记录，关联已有知识，不创建读取占用、提取任务或重复向量

#### Scenario: SDK 会话不得持久化源码原文
- **WHEN** 问答 Job 启用了代码分析能力
- **THEN** 禁用 SDK 会话转录和提示历史落盘，实际工具/权限/版本审计仍保留安全元数据；源码与 SVN 原文只在本次受限执行内传递
