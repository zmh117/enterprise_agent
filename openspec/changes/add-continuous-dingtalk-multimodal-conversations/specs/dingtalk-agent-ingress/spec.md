## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
系统 SHALL 解析并持久化钉钉Stream conversation身份、群聊或私聊类型、发送人、机器人身份、来源Channel、connector、外部事件、外部消息、可选文本和附件描述，以解析或复用session并创建job。

#### Scenario: User asks in a group
- **WHEN** 已验证群消息包含诊断文本
- **THEN** 系统持久化群conversation、发送人、事件、文本和稳定session归属

#### Scenario: User sends an attachment in direct chat
- **WHEN** 已验证私聊消息包含MVP支持附件并可选包含文本
- **THEN** 系统持久化参与方、外部消息、附件安全元数据和稳定私聊session归属

## ADDED Requirements

### Requirement: DingTalk Stream支持MVP媒体入站
系统 SHALL 将钉钉JPEG/PNG/WebP图片及DOCX/XLSX/PPTX/Markdown文件归一化为Channel附件，并安全拒绝未支持媒体。

#### Scenario: Supported DingTalk image arrives
- **WHEN** Stream adapter收到有效的MVP图片媒体引用
- **THEN** adapter创建图片attachment并进入受控下载和存储流程

#### Scenario: Supported DingTalk document arrives
- **WHEN** Stream adapter收到有效现代Office或Markdown媒体引用
- **THEN** adapter创建文档attachment并保留事件、消息和附件序号幂等关系

#### Scenario: Unsupported DingTalk media arrives
- **WHEN** adapter收到DOC/XLS/PPT、PDF、压缩包、音视频或未知媒体
- **THEN** 系统不解析内容并返回不会触发无穷重投的安全确认

### Requirement: 附件处理不阻塞Stream快速确认
系统 SHALL 在持久化session、message、attachment和WAITING_INPUT job后快速ACK，并异步下载与提取附件。

#### Scenario: Supported document is accepted
- **WHEN** 文档符合入口数量和声明大小限制
- **THEN** Stream入口先确认接收，job等待附件终态后再进入Agent队列

### Requirement: 钉钉媒体凭证保持短寿命
系统 SHALL 使用受控钉钉客户端获取媒体，MUST NOT持久化或记录download code、临时URL、access token或session webhook。

#### Scenario: Media download succeeds
- **WHEN** adapter使用有效临时凭证下载附件
- **THEN** 系统只保存内部对象引用、散列和安全来源摘要并清除临时凭证
