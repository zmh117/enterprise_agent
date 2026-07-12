## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
系统 SHALL 解析并持久化创建或复用Agent session及创建Agent job所需的钉钉Stream conversation身份、群聊或私聊类型、发送人身份、机器人/应用身份、来源Channel、connector、外部事件、外部消息、可选文本正文和附件描述。

#### Scenario: User asks a text diagnostic question in a group
- **WHEN** 一个已验证钉钉Stream群消息包含用户诊断文本
- **THEN** 系统持久化群conversation身份、会话类型、发送人、来源、事件、原始文本和稳定session归属

#### Scenario: User sends an attachment in a direct chat
- **WHEN** 一个已验证钉钉Stream私聊消息包含受支持附件并可选包含文本
- **THEN** 系统持久化私聊参与方身份、外部消息身份、附件安全元数据和稳定私聊session归属

## ADDED Requirements

### Requirement: DingTalk Stream支持受控图片和文件入站
系统 SHALL 将钉钉图片和文件消息归一化为Channel附件，并支持策略允许的图片、DOC/DOCX、XLS/XLSX、PPT/PPTX和Markdown格式。未知事件或未支持格式 MUST 被安全忽略或拒绝并审计。

#### Scenario: DingTalk image message is received
- **WHEN** Stream adapter收到带有效图片媒体引用的已认证消息
- **THEN** adapter创建图片attachment描述并进入受控下载、扫描和处理流程

#### Scenario: DingTalk Office file message is received
- **WHEN** Stream adapter收到带有效文件媒体引用和文件名的已认证消息
- **THEN** adapter创建文档attachment描述并保留外部消息与附件序号的幂等关系

#### Scenario: Unsupported DingTalk media is received
- **WHEN** Stream adapter收到音频、视频、压缩包、可执行文件或无法识别的媒体事件
- **THEN** 系统不执行或解析媒体内容，记录安全原因并返回不触发重复重投的确认语义

### Requirement: DingTalk附件下载不阻塞Stream快速确认
系统 SHALL 在持久化session、message、attachment和等待输入的job后快速确认Stream事件，并异步完成媒体下载和提取。系统 MUST NOT 等待Office解析或图片内容提取完成后才返回ACK。

#### Scenario: Large supported document is accepted
- **WHEN** 钉钉发送一个未超过策略上限但需要异步解析的文档
- **THEN** Stream入口在持久化内部记录后立即确认接收，job等待附件终态后再进入Agent队列

### Requirement: DingTalk临时媒体凭证保持短寿命
系统 SHALL 使用钉钉授权客户端换取或下载媒体，但 MUST NOT 持久化或记录完整download code、临时URL、access token或session webhook。

#### Scenario: Media download succeeds
- **WHEN** adapter使用有效临时凭证下载附件
- **THEN** 系统只保存内部对象引用、内容散列和安全来源摘要，并从处理上下文清除临时凭证

