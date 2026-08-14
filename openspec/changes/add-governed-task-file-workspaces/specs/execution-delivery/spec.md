## ADDED Requirements

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job 创建事务 MUST 固定任务工作区ID和Job File Manifest中的精确File/Version ID，并将该清单以有界、无正文、无凭据形式交给所选Runtime。Runtime按需物化时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界；不得读取清单外或之后产生的版本。

#### Scenario: 执行期间当前版本变化
- **WHEN** Job固定V3后另一Job提交V4
- **THEN** 当前Runtime仍只物化V3
- **AND** 基于V3的后续提交按正常并发规则得到冲突

### Requirement: Runtime 管理单 Job 文件沙盒
Python与TypeScript Runtime MUST 为每次调用创建隔离Job Sandbox，以受控映射保存本地相对路径、File ID和基础Version ID，并在成功、失败、取消或超时终态清理。启动恢复或周期扫描 MUST 清理没有RUNNING Job归属的残留沙盒；目录不得跨Job复用或持久化。

#### Scenario: Runtime进程异常退出
- **WHEN** Job Sandbox未执行正常finally清理且对应Job已经不再RUNNING
- **THEN** 恢复扫描删除该目录
- **AND** 后续Job不能看到其内容

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST 通过File Service受控流式接口下载Job File Manifest中的精确版本和上传显式选中的沙盒文件。File MCP只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT 进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

#### Scenario: Agent显式提交沙盒文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控沙盒文件
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、版本、大小、哈希摘要和结果

### Requirement: 文件提交结果不扩展 Job 终态枚举
系统 MUST 为每个File Commit Intent保存独立业务结果，部分提交冲突或拒绝不得回滚其它成功版本。Runtime能持久化最终回复并准确报告文件结果时，Job SHALL使用现有`SUCCEEDED`；系统 MUST NOT 新增`PARTIAL` Job状态。只有Runtime整体执行失败、超时或无法产生最终回复时才使用现有失败类终态。

#### Scenario: 部分文件提交冲突
- **WHEN** 一个Job的两个文件成功且一个文件冲突，Runtime正常返回说明
- **THEN** Job为`SUCCEEDED`
- **AND** 每个提交保留独立结果

### Requirement: 钉钉文件结果按精确版本创建独立交付
钉钉用户明确要求修改或生成文件时，成功提交的精确File Version SHALL 默认创建回当前reply route的文件交付意图，用户明确要求只保存到工作区时除外。第一阶段交付 MUST 创建新的钉盘文件并记录新外部引用、精确Version ID和输入来源血缘，不得覆盖输入原件、交付冲突候选或跨会话发送。

#### Scenario: 群聊生成TXT结果
- **WHEN** 群聊Job按用户请求成功提交一个新TXT版本
- **THEN** 系统为当前群reply route创建该精确版本的新钉盘文件交付
- **AND** 原输入钉盘文件保持不变

#### Scenario: 用户要求只保存
- **WHEN** 用户明确要求结果只保存在任务工作区
- **THEN** 系统提交版本但不创建文件交付意图

### Requirement: 文件版本提交与文件交付使用独立状态机
文件版本通过校验并提交后 MUST 保持当前版本，即使随后钉钉文件交付失败。Delivery重试 MUST 固定同一个File Version和交付意图，不得重跑Agent、生成另一份内容、回滚版本或改变已`SUCCEEDED`的Job。工作区到期时存在非终态交付 SHALL 只暂缓该精确内容清理；成功交付使该版本成为Retained File，最终失败后若工作区已到期则立即清理临时内容。

#### Scenario: 文件交付暂时失败
- **WHEN** File Version已提交但钉钉上传超时
- **THEN** Delivery进入自身重试状态且Job与当前版本保持不变
- **AND** 重试仍发送同一内容哈希的精确版本

## MODIFIED Requirements

### Requirement: Read-only tools are exposed only through the deployment-fixed standard MCP server
系统 SHALL 让两个独立Runtime通过部署固定的标准`tool-mcp`访问Job冻结的只读MCP Tool，并通过部署固定的`file-service` File MCP接口访问Job冻结的任务文件工具。Runtime MUST NOT注册旧Capability Tool、接受任意Server URL、在Tool不可用时fallback或把文件工具路由到`tool-mcp`。`tool-mcp`继续使用非认证Job绑定传输；File MCP MUST使用平台短时Principal JWT并在服务端复核主体、Job、Publication、scope和任务工作区。

#### Scenario: Python Runtime调用允许的只读Tool
- **WHEN** Python SDK调用Job精确允许的只读MCP Tool
- **THEN** 调用通过标准MCP SDK进入部署固定`tool-mcp`并返回安全结果

#### Scenario: TypeScript Runtime调用允许的文件Tool
- **WHEN** TypeScript SDK调用Job精确允许的File MCP Tool
- **THEN** 调用只进入部署固定`file-service`且携带不含下游Secret的Principal JWT

#### Scenario: Tool上下文按Job隔离
- **WHEN** 两个Runtime并发调用相同只读或文件Tool
- **THEN** 每次调用使用各自Job、Publication和scope且不共享模型或MinIO凭据

#### Scenario: 模型提供任意MCP地址
- **WHEN** 请求内容或模型输出尝试注册未冻结MCP Server URL或Tool
- **THEN** Runtime与服务端失败关闭

#### Scenario: 旧平台对象被配置
- **WHEN** 启动或执行配置包含旧Capability、Handler、Resource Mapping、Internal API Token、`RUNTIME_TOOL_MCP_*`或HS256 signing key
- **THEN** 部署预检失败且不启动兼容模式

### Requirement: Built-in mutating tools are disabled
系统 SHALL 继续禁止SDK的Bash、NotebookEdit、WebFetch、WebSearch、Shell、部署、数据库写入和其它开放执行工具。只有启用任务文件工作区且Job冻结精确File MCP Tool时，Runtime MAY向Claude Code开放`Read`、`Grep`、`Write`和`Edit`，并 MUST 把目标限制到当前Job Sandbox、拒绝路径穿越与符号链接逃逸。文件系统修改只改变本地副本，必须经File Service显式提交才能形成文件版本。

#### Scenario: Model attempts Bash or Web tool
- **WHEN** SDK尝试调用Bash、WebFetch、WebSearch或NotebookEdit
- **THEN** 该工具不可用或调用被拒绝

#### Scenario: Model edits inside the Job Sandbox
- **WHEN** 已授权文件Job调用`Write`或`Edit`且规范化目标位于当前Job Sandbox
- **THEN** Runtime允许本地文件操作并保留有界工具结果
- **AND** 不直接写MinIO或创建文件版本

#### Scenario: Model edits outside the Job Sandbox
- **WHEN** `Write`或`Edit`目标离开当前Job Sandbox或Job未冻结文件工具
- **THEN** Runtime在副作用前拒绝

#### Scenario: Only current MCP set is auto-approved
- **WHEN** Application Publication只选择一个MCP Tool
- **THEN** 只有该Tool及其要求的受限本地文件工具可进入allowedTools和自动批准集合

#### Scenario: Application has no Tool
- **WHEN** Application MCP Tool子集为空
- **THEN** 不注册或批准任何平台Tool或本地文件修改工具

### Requirement: Runtime exposes only read-only tools
系统 SHALL 默认只注册Job冻结的只读MCP Tool。仅当Business Application与Agent Publication都冻结支持的File MCP Tool且当前Job绑定有效任务工作区时，Runtime SHALL 额外注册部署固定File MCP Server及沙盒受限`Read`、`Grep`、`Write`和`Edit`；数据库更新、Redis删除、重启、部署、PR创建、任意Shell和沙盒外文件操作仍 MUST 被拒绝。

#### Scenario: Diagnostic Job asks for a mutating tool
- **WHEN** 普通诊断Job没有文件工具却请求代码修改、数据库更新、Redis删除、重启、部署或沙盒执行
- **THEN** 系统因工具未注册或被拒绝而阻止调用

#### Scenario: File Job uses registered sandbox tools
- **WHEN** 文件Job调用Job冻结的File MCP Tool和当前沙盒受限文件工具
- **THEN** 调用分别通过File Service与Runtime路径守卫执行
- **AND** 不经过旧`ToolRegistry`动态实现或任意Server

### Requirement: Runtime必须隔离SDK配置和工具权限
每次SDK调用 MUST 使用独立options、env和Job Sandbox，显式设置`settingSources: []`，仅注册请求固定的`tool-mcp`和/或File MCP Server，并以精确`allowedTools`和deny-by-default `canUseTool`限制Tool。Bash、NotebookEdit、WebFetch、WebSearch、Shell和开放文件修改能力 MUST 被禁用；文件Job的`Read`、`Grep`、`Write`与`Edit`必须经过当前沙盒路径守卫。

#### Scenario: 模型调用允许的只读Tool
- **WHEN** Job请求固定了合法只读MCP Server、Tool、schema hash和scope
- **THEN** Runtime只允许对应`mcp__<server>__<tool>`调用并由MCP服务再次复核Job和scope

#### Scenario: 模型调用允许的文件Tool
- **WHEN** Job请求固定了合法File MCP Tool且Principal JWT、schema hash和scope匹配
- **THEN** Runtime只连接部署固定File Service并把本地文件工具限制到当前Job Sandbox

#### Scenario: 模型尝试调用未授权工具
- **WHEN** 模型请求Bash、Web工具、沙盒外文件操作或不在精确集合中的MCP Tool
- **THEN** Runtime拒绝调用且不向任何Tool backend发出请求
