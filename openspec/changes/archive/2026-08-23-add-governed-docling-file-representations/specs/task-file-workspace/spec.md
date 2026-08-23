## ADDED Requirements

### Requirement: 原始文件与Agent可读表示使用不同身份和动作
File Service MUST 把PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP作为受治理原始File Version保存，并把Docling Markdown与Docling JSON作为关联该精确版本的不可变Representation保存。原始文档动作 SHALL 限于`READ_METADATA`、`RETAIN`和`DELIVER`；Markdown representation只允许受控`MATERIALIZE`，Docling JSON第一阶段不得向Agent物化。系统不得把representation提升为原文件版本、允许原始二进制进入沙盒，或允许Agent直接编辑/提交Office、PDF和图片版本。

#### Scenario: Agent总结PDF
- **WHEN** Job Manifest冻结一个PDF source Version及其Markdown representation
- **THEN** Runtime物化Markdown而不物化PDF二进制
- **AND** Agent使用Read、Grep或Glob按需读取Markdown

#### Scenario: 用户要求转发原始PDF
- **WHEN** 用户要求交付Manifest中具有DELIVER动作的原始PDF版本
- **THEN** Delivery通过File Service读取精确source Version并发送原件
- **AND** 不发送Markdown representation

#### Scenario: 用户要求直接修改DOCX
- **WHEN** 用户要求保留原版式直接修改DOCX
- **THEN** 系统说明第一阶段只支持读取派生文字和生成新的受支持文本文件
- **AND** 不把Markdown修改伪装成DOCX新版本

## MODIFIED Requirements

### Requirement: 第一阶段文件类型和配额有界
任务工作区 SHALL 根据Business Application Publication冻结的文本格式策略继续支持TXT及已发布的LOG/Markdown能力，并在Publication选择`docling-text-v1`时接受PDF、DOCX、XLSX、PPTX、PNG、JPEG和WebP原件。文本文件和Agent可读Markdown单文件最大15MiB，Docling源文件最大25MiB且PDF最多300页；每个工作区最多20个逻辑文件，尚未成为保留文件的工作版本、冲突候选和工作区派生内容计费总量必须受代码发布Profile限制。新导入、处理或提交导致任一上限被突破时 MUST 在创建可见版本或表示前完整拒绝。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其它未支持格式，且不得静默截断、猜测编码或降级到宽松解析器。

#### Scenario: 非UTF-8文本进入工作区
- **WHEN** TXT、LOG或Markdown内容是GBK、UTF-16或无效UTF-8
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测或自动转换编码

#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本或派生表示会使工作区计费临时内容超过冻结上限
- **THEN** File Service不创建对象可见性、文件版本、representation或错误的当前指针

#### Scenario: 受支持PDF到达
- **WHEN** 新任务工作区收到不超过25MiB和300页、MIME与结构合法的PDF且Publication冻结`docling-text-v1`
- **THEN** File Service保存原件并异步生成Markdown和Docling JSON表示
- **AND** 原始PDF不直接进入Agent Sandbox

#### Scenario: 文档处理Profile未启用
- **WHEN** 工作区收到Office、PDF或图片但Publication没有冻结受支持文档处理Profile
- **THEN** 系统返回明确未启用结果
- **AND** 不调用Docling或声称已解析

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发Agent Job时，按当前用户、tenant、任务工作区、Business Application Publication和授权范围冻结Job File Manifest。直接可读文本条目 MUST 指向当时精确File Version；需文档处理的条目 MUST 同时冻结原始File/Version ID与精确Markdown Representation ID、kind、size、SHA-256和安全物化名。该文字Job本轮确定性绑定且能力已就绪的附件、同一消息新上传附件和明确引用文件 SHALL 自动物化；其他文件只提供不含正文、凭据和对象位置的元数据，由Agent按需选择。系统 MUST NOT 把工作区全部未挂接Job的附件自动列入物化集合。清单冻结身份但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT单独生成Manifest。

Job File Manifest、File MCP文件列表/元数据和Runtime自动物化元数据 MUST 明确区分：原始聊天附件进入平台的`source_received_at`、精确原始版本产生的`version_created_at`、representation产生时间以及Manifest冻结或查询发生的`observed_at`。`source_received_at` MUST 取平台创建原始`message_attachment`记录的时间并在后续版本/表示中保持不变；无聊天附件来源的Agent生成文件 MUST 返回`null`。持久化、Manifest hash、File MCP列表/元数据、Runtime Manifest和自动物化元数据中的非空机器时间 MUST 使用表示同一瞬时的UTC RFC 3339；面向用户陈述时才按用户显示时区转换，不得把`Z`或`+00:00`墙钟直接解释为本地时间。系统 MUST NOT使用File Worker导入完成时间、processing run时间、representation时间、工作区引用时间、Manifest条目时间或含义模糊的`created_at`回答“上传时间”。Manifest schema v4 MUST 把源身份、表示身份、来源接收时间和版本创建时间纳入不可变条目及其hash；旧schema可兼容读取但不得虚构缺失时间或表示。

#### Scenario: 暂存文本附件已经完成导入
- **WHEN** 后续非空文字创建Job前，暂存文本附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本冻结为自动物化项

#### Scenario: 暂存文档仍在处理
- **WHEN** 后续非空文字未绑定该文档
- **THEN** 系统立即创建可执行Job且不自动物化处理中文档
- **AND** 该文档继续作为工作区元数据候选

#### Scenario: 其他Job在执行期间产生新表示
- **WHEN** 当前Job清单冻结source V3和representation R1后，同一source Version产生R2或文件产生V4
- **THEN** 当前Job继续物化R1并继续把V3用于原件身份
- **AND** R2或V4只进入后续新Job清单

#### Scenario: 冻结后用户权限被撤销
- **WHEN** 文件和representation仍在Job File Manifest中但当前用户或应用访问已失效
- **THEN** File Service拒绝物化或交付
- **AND** 不把冻结清单解释为长期访问授权

#### Scenario: 查询最近一小时上传的文件
- **WHEN** 用户要求处理最近一小时上传的工作区文件
- **THEN** Agent使用File Service返回的`observed_at`作为边界，只选择`source_received_at`不早于该边界减一小时的文件
- **AND** 不把后续编辑版本或新representation误判为新上传文件

#### Scenario: Agent生成文件没有上传时间
- **WHEN** 工作区文件由Agent生成且没有聊天附件来源
- **THEN** File Service返回`source_received_at=null`和非空`version_created_at`
- **AND** Agent不把该文件归入“最近上传的附件”集合

#### Scenario: Manifest尝试替换Representation
- **WHEN** 模型或Runtime尝试以Manifest外的representation ID替换冻结表示
- **THEN** File Service在读取内容前拒绝

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST 为每个Agent Job创建独立Job Sandbox，并只把当前Job已授权的精确文本File Version或精确Markdown Representation物化到该目录。PDF、Office、图片原始二进制和Docling JSON MUST NOT进入Agent Sandbox。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，且写/编辑动作仍受冻结文本格式策略限制；Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST 保持不可用。Job成功、失败、取消或超时后 MUST 清理沙盒，Runtime异常退出后 MUST 由恢复扫描清理无RUNNING Job归属的残留目录。

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
