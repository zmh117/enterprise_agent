## MODIFIED Requirements

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job工作集已授权的精确文本File Version或精确Markdown Representation物化到该目录。Sandbox MUST固定总文件上限64和总容量224MiB，并分别限制`inputs`最多40个文件、`work/outputs`合计最多16个文件、`tmp`及内部安全余量最多8个文件；目录、marker和不可见控制元数据不得被模型用来规避普通文件计数。PDF、Office、图片原始二进制、Docling JSON和OCR Layout JSON MUST NOT进入Agent Sandbox。

自动物化、File MCP按需物化、Runtime Write/Edit、日志证据扫描生成的临时`work/`证据包和内部临时文件 MUST共享同一Sandbox预算与原子预留器。Runtime在写入第一个自动物化字节前 MUST对整批输入重新预留实际文件数与Manifest冻结大小；按需物化、写入和日志证据扫描 MUST在创建目标文件前预留对应分区名额和剩余容量。失败或完整性校验不通过 MUST删除不完整文件并释放预留。重复物化同一`file_id + version_id` MUST复用已有输入和handle，不重复占用文件数或字节。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，以及在当前Job冻结只读物化能力时使用Runtime派生的`scan_log_evidence`；写/编辑动作仍受代码固定`text-v2`格式矩阵限制。Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无RUNNING Job归属的残留目录。

#### Scenario: Agent读取PDF派生Markdown
- **WHEN** Job获得受控PDF source Version及其Markdown representation
- **THEN** Runtime只在安全inputs路径物化经过大小和SHA-256校验的Markdown
- **AND** 本地副本不改变MinIO、原始版本或representation

#### Scenario: Agent在沙盒内编辑文本输出
- **WHEN** Job按冻结文本策略获得可写TXT或Markdown并调用Edit
- **THEN** Runtime只允许规范化后仍位于该Job沙盒的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试写沙盒外路径
- **WHEN** `Write`或`Edit`目标通过绝对路径、`..`、符号链接或其它方式离开Job Sandbox
- **THEN** Runtime在文件系统副作用前拒绝并记录安全工具结果

#### Scenario: Agent尝试读取原始二进制
- **WHEN** Agent或Runtime请求把PDF、Office或图片source Version直接物化到沙盒
- **THEN** File Service拒绝并只允许Manifest冻结的Markdown representation路径

#### Scenario: Agent在沙盒内编辑Markdown
- **WHEN** `text-v2` Job获得受控`.md`文件并调用`Edit`
- **THEN** Runtime只允许规范化后仍位于该Job沙盒且format允许`EDIT`的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试编辑LOG
- **WHEN** Agent对沙盒内`.log`调用`Write`或`Edit`
- **THEN** Runtime在文件系统副作用前以稳定只读格式错误拒绝
- **AND** 不允许通过改名、绝对路径或handle复用绕过

#### Scenario: Agent读取Office派生Markdown
- **WHEN** Job工作集获得受控DOCX source Version及其Markdown representation
- **THEN** Runtime只在安全`inputs`路径物化经过大小和SHA-256校验的Markdown并计为一个输入
- **AND** 原始DOCX、Docling JSON和内嵌图片不进入Sandbox

#### Scenario: File MCP物化达到输入上限
- **WHEN** Sandbox已经成功物化40个不同File/Version输入且Agent请求第41个
- **THEN** Runtime与File Service在创建目标文件前拒绝`job_file_working_set_limit_exceeded`
- **AND** 不创建transfer残留、Sandbox文件或第41个有效工作集输入

#### Scenario: 输入文件数未满但容量不足
- **WHEN** 下一份Markdown会使Sandbox实际文件总量超过224MiB
- **THEN** 统一预算在下载字节前拒绝并返回安全容量错误
- **AND** 不因File MCP路径不同而绕过Write/Edit使用的容量边界

#### Scenario: Agent在沙盒内生成输出
- **WHEN** 40个输入均已占用且`work/outputs`仍有分区名额和总字节余量
- **THEN** Runtime允许在16个输出/工作文件上限内创建受支持文本
- **AND** 输入文件数不得消耗输出分区名额

#### Scenario: 日志扫描证据包占用工作分区
- **WHEN** Runtime准备为已物化LOG生成一个证据包
- **THEN** 证据包在读取首个输入字节前原子预留一个`work/outputs`文件名额和代码固定的最大容量
- **AND** 不得挤占输入分区名额、绕过224MiB总容量或把未完成文件暴露给模型

## ADDED Requirements

### Requirement: Runtime 对已物化 LOG 提供单次有界证据扫描
Runtime SHALL提供代码发布且schema固定的`scan_log_evidence`本地工具，在一次调用中逐文件顺序扫描当前Job已经物化的1至40个唯一`inputs/*.log`。工具 MUST只接受安全POSIX相对路径、有界字面关键词、有界上下文行数和有界证据条目数；MUST拒绝File/Version ID、对象键、URL、输出路径、解析Profile、时间格式、字段映射、正则、代码、Shell或其它可执行表达式。每个输入 MUST重新验证为当前Sandbox已提交的普通只读LOG且不是符号链接；工具不得读取沙盒外路径、调用网络、连接MinIO或扩大当前Job文件权限。

扫描器 MUST以有界内存遍历每个输入的全部字节，计算逐文件和总体的实际大小、已扫描字节、逻辑行数和内容SHA-256。候选证据 SHALL仅来自代码固定且版本化的通用故障/级别标志、调用方提供的字面关键词以及保守多行上下文；任何时间、级别、用户、操作或业务语义无法可靠确定时 MUST标记为未知或省略，不得猜测日志格式。扫描器 MUST把精确扫描事实与启发式证据选择分开报告。

#### Scenario: 扫描多个异构LOG
- **WHEN** 当前Job已经物化20个格式不同且合计不超过Sandbox剩余预算的有效UTF-8 LOG，并在一次调用中选择这些路径
- **THEN** 扫描器顺序读取每个文件到EOF并返回逐文件和总体的精确扫描字节与逻辑行数
- **AND** 未识别的时间、级别或业务字段标记为未知，不因格式不同拒绝整批扫描

#### Scenario: 请求未物化或非LOG路径
- **WHEN** `relative_paths`包含不存在路径、`work/`路径、非LOG文件、符号链接、绝对路径、反斜杠或`..`
- **THEN** Runtime在读取任何目标正文或创建证据包前完整拒绝该调用
- **AND** 不自动物化文件、不扫描其它输入且不产生部分成功结果

#### Scenario: 模型提交任意解析表达式
- **WHEN** Tool输入包含正则、脚本、Profile、字段映射、时间格式或未知字段
- **THEN** Runtime按固定schema在执行扫描前拒绝
- **AND** 不把该值解释、编译或传给文件系统工具

#### Scenario: 输入存在超长无界记录
- **WHEN** 单行或候选多行块超过代码固定的内部缓冲上限
- **THEN** 扫描器以稳定错误终止并清理未完成证据包
- **AND** 不截断该记录后声称扫描完整

### Requirement: 日志证据包有界、可定位且不会伪装完整语义审查
成功扫描 SHALL在当前Job的`work/`分区生成一个确定命名的UTF-8 Markdown证据包，文件名由scanner版本、已物化输入身份/内容hash和规范化参数的摘要产生，文件最大4MiB。证据包 MUST记录scanner版本、输入身份安全摘要、逐文件和总体覆盖、候选/保留/省略计数、限制标志；每条保留证据 MUST包含输入相对路径、起止行、起止字节、精确片段hash、命中类型和当前Job授权下的原文片段。原文 MUST使用确定性转义或无法被原文闭合的代码块封装并标为不可信数据，日志中的指令、Tool名、Markdown或HTML不得改变Runtime安全规则或触发Tool调用。证据包不得改变原LOG、成为其新File Version或自动进入File Commit/Delivery。

达到条目或4MiB证据上限时，扫描器 MUST继续扫描所有选中输入到EOF，并设置`evidence_limit_reached=true`与省略候选计数；不得把有界选择描述为全部日志已经被语义理解。Tool JSON响应 MUST只返回证据包相对路径、大小、SHA-256、覆盖计数、候选/保留/省略计数和限制标志，不得包含证据正文。

#### Scenario: 证据候选超过包上限
- **WHEN** 全量扫描发现的候选证据无法全部放入条目或4MiB上限
- **THEN** 扫描器继续读取所有输入到EOF并成功返回完整字节覆盖统计
- **AND** 证据包明确记录限制命中和省略数量，Tool响应不包含被省略正文

#### Scenario: 相同请求在同一Sandbox重复执行
- **WHEN** scanner版本、规范化参数和所有输入身份/内容hash与先前成功请求完全相同
- **THEN** Runtime验证既有证据包大小与SHA-256后复用同一路径和结果
- **AND** 不重复扫描、不创建第二个工作文件或重复占用Sandbox预算

#### Scenario: 相同路径内容事实不一致
- **WHEN** 重复请求发现已物化输入的实际大小或SHA-256与Sandbox提交身份不一致
- **THEN** Runtime以完整性错误失败并拒绝复用既有证据包
- **AND** 不返回旧覆盖事实或旧证据作为当前结果

#### Scenario: 用户要求保存最终报告
- **WHEN** Agent读取证据包后生成用户要求的Markdown报告
- **THEN** Agent另行写入受支持的`outputs/`或`work/`Markdown，并显式执行既有选择输出与Commit Intent流程
- **AND** 扫描器不自动提交证据包、报告或原LOG

#### Scenario: 原日志包含提示注入样式文本
- **WHEN** 证据片段包含“忽略系统指令”、Tool名、Markdown围栏、HTML或类似可执行指示
- **THEN** 证据包将其封装并标记为不可信原文数据
- **AND** Runtime不把该内容提升为指令、工具授权或文件操作

### Requirement: 日志扫描失败与取消必须完整清理
Runtime MUST在创建日志证据包前执行原子Sandbox预留，并让扫描服从当前attempt的取消信号与剩余墙钟预算。容量不足、读取失败、内容完整性失败、写入失败、取消或超时 MUST删除未完成证据包、释放文件与字节预留并返回稳定安全错误；只有全部输入扫描完成且证据包flush、UTF-8和SHA-256校验成功后才能返回成功与`coverage_complete=true`。

#### Scenario: 200MiB输入后剩余容量不足
- **WHEN** 已物化输入和现有工作文件使Sandbox无法同时预留一个证据包与现有输出安全余量
- **THEN** Runtime在扫描首个输入字节前完整拒绝并返回Sandbox容量错误
- **AND** 不创建空文件、部分证据包或新的持久化对象

#### Scenario: 扫描中收到取消
- **WHEN** Runtime在读取输入或写入证据包期间收到Job取消或墙钟耗尽信号
- **THEN** 扫描器合作式停止、删除未完成内容并释放预留
- **AND** 不返回`coverage_complete=true`或可供模型读取的部分路径

#### Scenario: 所有输入和证据包校验成功
- **WHEN** 扫描器已经读取全部选中输入到EOF且证据包通过大小、UTF-8和SHA-256校验
- **THEN** Runtime原子发布证据包路径并返回`coverage_complete=true`
- **AND** 后续Job成功、失败、取消或超时时证据包仍随Sandbox统一清理
