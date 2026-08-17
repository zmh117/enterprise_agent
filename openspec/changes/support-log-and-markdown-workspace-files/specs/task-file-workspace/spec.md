## MODIFIED Requirements

### Requirement: 第一阶段文件类型和配额有界
任务工作区 MUST 按 Publication 与 Job 冻结的代码注册文件格式策略失败关闭。`text-v1`保持只接受UTF-8 `.txt`；`text-v2`固定支持 `.txt`全能力、`.log`只读和既有精确版本交付、`.md`全能力。三种格式输入均可包含UTF-8 BOM，Agent生成的 `.txt/.md` MUST为无BOM UTF-8；GBK、UTF-16、无效UTF-8、NUL或其它二进制内容 MUST拒绝。单文件最大15 MiB，每个工作区最多20个逻辑文件，尚未成为保留文件的工作版本和冲突候选合计最多100 MiB。新提交导致任一上限被突破时 MUST在创建正式版本前完整拒绝。`.markdown`、Office、PDF、图片及其它格式不进入本阶段任务工作区，系统 MUST NOT部署或调用`docling-serve`。

#### Scenario: UTF-8 LOG进入text-v2工作区
- **WHEN** `.log`内容为有效UTF-8、无NUL且不超过15 MiB，并命中冻结的`text-v2`
- **THEN** File Service保存不可变精确版本并标记format为`LOG`
- **AND** 允许的操作只包含读取和既有版本交付

#### Scenario: Markdown进入text-v2工作区
- **WHEN** `.md`内容为有效UTF-8且不超过15 MiB，并命中冻结的`text-v2`
- **THEN** File Service允许导入、读取、创建、编辑、提交和交付
- **AND** 内容始终作为不可信纯文本而不渲染HTML或抓取远程资源

#### Scenario: 非UTF-8文本进入工作区
- **WHEN** `.txt`、`.log`或`.md`内容是GBK、UTF-16、无效UTF-8、包含NUL或其它二进制内容
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测、转换编码或创建部分对象可见性

#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本会使工作区计费临时内容超过100 MiB
- **THEN** File Service不创建对象可见性、文件版本或错误的当前指针

#### Scenario: 未纳入策略的格式到达
- **WHEN** 新任务工作区链路收到`.markdown`、DOCX、XLSX、PPTX、PDF、图片或其它未注册格式
- **THEN** 系统返回明确不支持结果
- **AND** 不调用`docling-serve`、通用解析器或任意文件处理器

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job已授权的精确版本物化到该目录。Claude Code Agent只可在该沙盒内对冻结策略允许的`.txt/.log/.md`使用`Read`、`Glob`和`Grep`，并只可对`.txt/.md`使用`Write`和`Edit`；`.log`写入、Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无运行中Job归属的残留目录。

#### Scenario: Agent在沙盒内编辑Markdown
- **WHEN** `text-v2` Job获得受控`.md`文件并调用`Edit`
- **THEN** Runtime只允许规范化后仍位于该Job沙盒且format允许`EDIT`的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试编辑LOG
- **WHEN** Agent对沙盒内`.log`调用`Write`或`Edit`
- **THEN** Runtime在文件系统副作用前以稳定只读格式错误拒绝
- **AND** 不允许通过改名、绝对路径或handle复用绕过

#### Scenario: Agent尝试写沙盒外路径
- **WHEN** `Write`或`Edit`目标通过绝对路径、`..`、符号链接或其它方式离开Job Sandbox
- **THEN** Runtime在文件系统副作用前拒绝并记录安全工具结果

### Requirement: 提交暂存、校验和终结保持原子可恢复
File Service MUST在流式接收时计算内容哈希，并按Job冻结策略执行format、允许操作、逻辑扩展名、15 MiB大小和UTF-8校验；`.log` MUST在创建Commit Intent和接收正文前拒绝。终结前 MUST重新校验Job、工作区、文件归属、基础版本、format不变性和配额。暂存对象只有在对象完整且文件版本元数据事务成功后才能成为可见文件版本；失败或超时暂存不得进入文件列表或当前指针，并 MUST由`file-worker`可重试清理。

#### Scenario: LOG提交在接收正文前拒绝
- **WHEN** 调用方尝试为`.log` sandbox handle创建Commit Intent或上传新内容
- **THEN** File Service返回稳定的只读格式错误
- **AND** 不创建staging对象、文件版本或Delivery

#### Scenario: 修改既有文件时format发生变化
- **WHEN** Commit Intent引用既有File/Base Version但所选sandbox文件扩展名或format与基础版本不同
- **THEN** File Service在上传前拒绝
- **AND** 不把重命名LOG视为可写TXT或Markdown

#### Scenario: 对象接收完成但数据库事务失败
- **WHEN** 合法TXT或Markdown暂存对象完整写入后文件版本事务回滚
- **THEN** 对象保持不可见待清理状态
- **AND** 文件列表和当前版本不发生变化

#### Scenario: 暂存对象清理暂时失败
- **WHEN** MinIO删除发生瞬时错误
- **THEN** File Service保留待清理事实并由`file-worker`重试
- **AND** 不错误标记为已删除

### Requirement: 版本冲突由 Claude Code 显式处理
File Service MUST NOT对可写`.txt/.md`或后续Office类型自动合并，也不得覆盖当前版本。已上传但因并发产生冲突的结果只能成为按工作区生命周期管理的Conflict Candidate，不得成为当前版本或Retained File。用户继续处理时，后续新Job SHALL同时物化最新版本和冲突候选，由Claude Code根据用户指令生成合并结果，并以最新版本为基础重新显式提交。只读`.log`不得产生编辑冲突候选。

#### Scenario: 群成员并发编辑Markdown
- **WHEN** 两个Job都基于同一Markdown V3且第一个已提交V4
- **THEN** 第二个结果成为冲突候选而不覆盖V4
- **AND** File Service不自动执行Markdown文本合并或渲染

#### Scenario: 两个Job读取同一LOG
- **WHEN** 两个Job并发物化同一`.log`精确版本
- **THEN** 两者可以按授权读取但都不能提交新版本
- **AND** File Service不创建LOG冲突候选
