## ADDED Requirements

### Requirement: 文件格式策略使用版本化跨Runtime契约
系统 MUST通过新的Runtime protocol版本向Python与TypeScript Runtime投影Job冻结的`file_format_policy_version`，并为每个Job File Manifest条目提供规范化format code、精确版本和允许操作集合。两个Runtime MUST从同一语言无关schema生成契约类型，并对`text-v1/text-v2`、扩展名、MIME、BOM、NUL、大小、路径与操作执行等价验证；未知策略版本、未知format、操作扩大或协议字段缺失 MUST在模型和文件系统副作用前失败关闭。旧Runtime protocol和旧Job MUST继续解释为TXT-only，不得因新Runtime部署获得LOG或Markdown能力。

#### Scenario: text-v2 Job进入两个Runtime
- **WHEN** 同一`text-v2` Job夹具分别由Python和TypeScript Runtime解析
- **THEN** 两端都允许读取`.txt/.log/.md`、只允许写入和选择`.txt/.md`
- **AND** 对相同非法路径、编码、大小和LOG写入返回等价稳定错误

#### Scenario: 旧Runtime收到text-v2 Job
- **WHEN** Job冻结`text-v2`但目标Runtime protocol不声明支持该策略
- **THEN** Worker或Runtime在模型调用前以不可重试配置错误失败
- **AND** 不回退到`text-v1`、另一Runtime或仅靠prompt约束

#### Scenario: Manifest操作集合被扩大
- **WHEN** Runtime请求中的LOG条目声明`EDIT`或`COMMIT`而冻结策略只允许`READ/DELIVER_EXISTING`
- **THEN** Runtime拒绝整个请求并记录不含文件名正文的安全协议错误
- **AND** 不物化或执行该Job

## MODIFIED Requirements

### Requirement: Built-in mutating tools are disabled
系统 SHALL继续禁止SDK的Bash、NotebookEdit、WebFetch、WebSearch、Shell、部署、数据库写入和其它开放执行工具。只有启用任务文件工作区且Job冻结精确File MCP Tool与受支持文件格式策略时，Runtime MAY向Claude Code开放`Read`、`Glob`、`Grep`、`Write`和`Edit`。`Read/Glob/Grep`只允许当前Job Sandbox内策略授权的`.txt/.log/.md`，`Write/Edit`只允许`.txt/.md`；所有工具 MUST拒绝路径穿越、符号链接逃逸、未知字段、未知扩展名和策略未授权操作。文件系统修改只改变本地副本，必须经File Service显式提交才能形成文件版本。

模型可见路径和模型提交的路径 MUST保持为安全相对路径。若Claude Code CLI在进入`canUseTool`前把该相对路径解析为基于`cwd`的绝对路径，Runtime MAY只在该绝对路径词法上属于本次随机Job Sandbox根、规范化后仍位于允许顶层且通过符号链接、常规文件、format与操作检查时，把它还原为相对路径继续授权；沙盒外绝对路径、相邻前缀路径和模型可见绝对路径能力 MUST继续拒绝。

#### Scenario: Model attempts Bash or Web tool
- **WHEN** SDK尝试调用Bash、WebFetch、WebSearch或NotebookEdit
- **THEN** 该工具不可用或调用被拒绝

#### Scenario: Model edits Markdown inside the Job Sandbox
- **WHEN** 已授权`text-v2`文件Job调用`Write`或`Edit`且目标为Sandbox内合法`.md`
- **THEN** Runtime允许本地文件操作并保留有界工具结果
- **AND** 不直接写MinIO、渲染Markdown或创建文件版本

#### Scenario: Model writes LOG inside the Job Sandbox
- **WHEN** 模型对Sandbox内合法`.log`调用`Write`或`Edit`
- **THEN** Runtime在副作用前以格式只读错误拒绝
- **AND** 路径位于Sandbox内不构成写授权

#### Scenario: SDK在权限回调前解析相对路径
- **WHEN** 模型调用`Write`使用安全相对`.txt/.md`路径且Claude Code CLI向`canUseTool`提供基于当前`cwd`解析的绝对路径
- **THEN** Runtime验证该路径精确属于本次Job Sandbox并将其还原为允许顶层下的相对路径后批准
- **AND** 真实CLI测试证明`canUseTool`被调用且文件实际写入本次沙盒

#### Scenario: Model edits outside the Job Sandbox
- **WHEN** `Write`或`Edit`目标离开当前Job Sandbox、使用未知格式或Job未冻结文件工具
- **THEN** Runtime在副作用前拒绝

#### Scenario: Only current MCP and sandbox set is exposed
- **WHEN** Application Publication只选择一个MCP Tool
- **THEN** 只有该Tool可进入MCP可调用集合，且只有文件Job所需的五个受限本地文件工具可进入SDK `tools`可用集合
- **AND** `allowedTools`/`allowed_tools`保持为空，所有调用仍经过`canUseTool`逐次校验

#### Scenario: Application has no Tool
- **WHEN** Application MCP Tool子集为空
- **THEN** 不注册或批准任何平台Tool或本地文件修改工具

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST通过File Service受控流式接口下载Job File Manifest中的精确`.txt/.log/.md`版本，并只上传显式选中的`.txt/.md`沙盒文件。File MCP只创建物化、提交或交付意图并返回不透明标识，完整文件字节 MUST NOT进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python与TypeScript Runtime MUST使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST使用当前Job File Principal JWT和固定内部流式路径，不得接受模型提供的URL、Header、Token、绝对路径、format覆盖或对象位置；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST将有界且无正文的Job File Manifest与冻结格式策略投影交给Runtime。Runtime MUST在模型请求前主动物化所有`auto_materialize=true`精确版本并向模型提供已校验的安全沙盒元数据；任何自动物化失败 MUST使Job失败关闭。其余候选只能由Agent使用Manifest中的精确File/Version ID按需物化。

#### Scenario: 当前消息文本附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含合法`auto_materialize=true`的当前消息TXT、LOG或Markdown精确版本
- **THEN** Runtime在首次模型请求前通过受控File bridge完成下载、format、大小和SHA-256校验及sandbox entry登记
- **AND** 模型只从安全相对路径读取且LOG entry不包含写操作

#### Scenario: Agent显式提交Markdown沙盒文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控`.md` sandbox handle
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、format、版本、大小、哈希摘要和结果

#### Scenario: Agent尝试提交LOG沙盒文件
- **WHEN** Agent把`.log`路径或handle传给输出选择器或提交工具
- **THEN** Runtime与File Service均在接收正文前拒绝
- **AND** 不创建Commit Intent、staging、版本或Delivery

#### Scenario: Runtime在模型看到结果前物化文件
- **WHEN** File Service为`file_prepare_materialization`返回合法隐藏传输控制信息
- **THEN** Runtime bridge在该ToolResult返回模型前完成流式下载、format、大小与SHA-256校验和sandbox entry登记
- **AND** 模型只收到安全相对路径、不透明handle、format、允许操作、大小和摘要

### Requirement: Runtime 显式选择单个沙盒输出
仅当当前Job冻结`file_create_commit_intent`和允许写入的文件格式策略时，Runtime SHALL注册代码自有的`select_sandbox_output`工具。该工具 MUST只接受当前Job Sandbox中安全相对`.txt/.md`路径，在返回不透明sandbox entry handle前校验路径边界、常规文件、无符号链接、format、15 MiB上限、UTF-8和无BOM输出；不得接受`.log`、返回正文、扫描目录或在Job结束时自动选择或提交其它文件。已物化且允许编辑的输入继续使用其既有handle。

#### Scenario: Agent选择新生成的Markdown
- **WHEN** Agent在`outputs/`或`work/`生成合法无BOM UTF-8 `.md`并显式调用`select_sandbox_output`
- **THEN** Runtime只为该精确文件创建本Job有效且绑定`MARKDOWN`的不透明handle并返回安全元数据
- **AND** 后续提交意图只能上传该handle映射的文件

#### Scenario: Agent选择LOG
- **WHEN** Agent对`outputs/`、`work/`或已物化输入中的`.log`调用`select_sandbox_output`
- **THEN** Runtime以格式只读错误拒绝
- **AND** 不通过改名或复制来源LOG自动获得提交授权

#### Scenario: Agent未选择其它草稿
- **WHEN** Job Sandbox中还存在未选择的其它文件并结束执行
- **THEN** Runtime不扫描、不上传且不提交这些文件
- **AND** finally清理整个Job Sandbox

### Requirement: 钉钉文件结果按精确版本创建独立交付
钉钉用户明确要求修改或生成TXT/Markdown时，成功提交的精确File Version SHALL默认创建回当前reply route的文件交付意图，用户明确要求只保存到工作区时除外。用户明确要求发送当前Manifest中获授权的既有TXT/LOG/Markdown时，系统 MAY创建该精确版本的交付意图但 MUST NOT修改内容或创建新版本。文件交付 MUST创建新的钉盘文件并记录新外部引用、精确Version ID和输入来源血缘，不得覆盖输入原件、交付冲突候选或跨会话发送。

当原reply route为钉钉Stream `sessionWebhook`时，普通文字回复 SHALL继续使用该Webhook；精确文件版本交付 MUST使用入站冻结的会话类型和来源Stream Connector应用凭据调用钉钉机器人OpenAPI，私聊目标为冻结的实际发送人，群聊目标为冻结的`openConversationId`。该专用途径 MUST只处理与原Job、原会话、原Connector绑定的`FILE_VERSION` Delivery，不得授予Stream Connector通用结果投递能力。

`file_deliver_version` SHALL接受当前Manifest中具有`DELIVER`动作的精确版本，或当前RUNNING Job自身`COMMITTED`提交意图产生的精确TXT/Markdown版本。对后者，File Service MUST复核Commit、Job、Workspace、Version、format、文件归属和内容可用性；不得要求把新输出补写进不可变输入Manifest，也不得仅凭模型提供的File/Version ID授权。

#### Scenario: 群聊生成Markdown结果
- **WHEN** 群聊Job按用户请求成功提交一个新Markdown版本
- **THEN** 系统为当前群reply route创建该精确版本的新钉盘文件交付
- **AND** 原输入钉盘文件保持不变且平台不渲染Markdown

#### Scenario: 私聊原样发送LOG
- **WHEN** 私聊Job按用户要求交付Manifest中具有`DELIVER`动作的既有LOG精确版本
- **THEN** 系统通过冻结reply route交付完全相同的版本和哈希
- **AND** 不创建Commit Intent、新文件版本或修改日志内容

#### Scenario: 用户要求只保存
- **WHEN** 用户明确要求TXT或Markdown结果只保存在任务工作区
- **THEN** 系统提交版本但不创建文件交付意图

#### Scenario: 私聊Stream文件与文字使用不同受控通道
- **WHEN** 私聊Job正常回复文字并成功提交默认交付的新Markdown版本
- **THEN** 文字结果通过冻结的`sessionWebhook`发送
- **AND** 文件版本通过来源Stream应用的私聊机器人OpenAPI发送给冻结的实际发送人

#### Scenario: 当前Job显式交付刚提交的新版本
- **WHEN** Agent对当前Job刚成功提交且不在输入Manifest中的精确TXT或Markdown版本调用`file_deliver_version`
- **THEN** File Service以提交意图来源证明授权并幂等返回同一Delivery状态
- **AND** 不返回“文件操作尚未就绪”或扩大Manifest
