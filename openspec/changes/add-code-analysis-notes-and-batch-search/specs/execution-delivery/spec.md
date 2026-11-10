## MODIFIED Requirements

### Requirement: Runtime 工具能力必须来自冻结集合与精确派生
Runtime MUST 只注册 Job 冻结 MCP 工具和代码允许的派生工具；只读资源走固定 `tool-mcp`，业务操作走对应固定业务 MCP，文件工具走 `file-service` bridge。业务 mutation 只准备受治理 Action Intent，须通过本规范逐次确认链才能产生 Provider 副作用。文件 Job 可使用受限 Read/Glob/Grep/Write/Edit；只冻结 ONES 集合查询而无文件写能力的 Job 仅派生 Read/Glob/Grep 读取结果文件。发布明确授权代码分析的问答 Job SHALL 在原 Job 内使用固定 Knowledge MCP 的 SVN/答案工具，并预先派生受限 Read/Glob/Grep 以及仅写当前执行 work/notes 下 Markdown/TXT 的 Write；源码读取必须在成功更新/检查后取得绑定当前 invocation 的共享读取 grant，不能仅凭挂载存在访问。grant 只收窄已冻结来源/路径/历史上限，不增加工具、仓库或动态挂载。代码只读挂载直接指向受管检出根，不经 File Service，不派生源码 Write/Edit 或 Shell；已有文件 Job 的权限保持独立。文件和 MCP 分别经过精确 hook/服务端授权，检查失败阻断。`select_sandbox_output` 依赖冻结提交能力，`scan_log_evidence` 依赖冻结物化能力与 Sandbox。Bash、Shell、NotebookEdit、WebFetch、WebSearch、任意部署、数据库写入和沙盒外操作 MUST 被拒绝。

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

#### Scenario: 纯代码任务写阶段笔记
- **WHEN** 代码 Job 使用派生 Write
- **THEN** 仅允许本次随机 Sandbox 的 work/notes 下 Markdown/TXT，不增加源码写入、Edit、文件提交或其他目录写能力
- **AND** 笔记不是已核验证据，Write 仍消耗工具和轮次预算，读工具审计与免计轮次不变

#### Scenario: 授权目录内批量源码定位
- **WHEN** 已取得版本 grant 的 Job 对授权目录或文件调用 Grep
- **THEN** Runtime 根据 SVN 元数据和 glob 筛选受管候选，逐一验证版本与内容并以规范化 UTF-8 只读临时副本执行搜索，返回原路径行号与有界上下文
- **AND** 每次最多 64 文件、32 MiB、200 输出行、前后各 5 行；枚举最多 10000 候选，超限明确要求缩小范围
- **AND** 不读取未跟踪文件或 .svn 到模型；受限内容跳过只暴露计数和不完整标记，版本/内容变化整次失败；命中须 Read 原源码取得证据 ID
