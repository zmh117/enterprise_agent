## MODIFIED Requirements

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT、LOG、Markdown、born-digital PDF、扫描PDF、DOCX、PPTX、XLSX、带文字图片和无文字图片及假凭据，证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、File Domain Outbox、processing RabbitMQ拓扑、File Processing Worker、Docling、Agent Worker、Python Runtime protocol 1.3、Job Sandbox、File MCP、原件Delivery和文本结果形成新鲜链路。验收还 MUST 覆盖无附件文字Job、Principal/API Key拒绝、越权文件、MIME伪装、加密/损坏/超大小/超页数、PARTIAL、NO_TEXT、Markdown超限、Docling重启、结果取得后Worker崩溃、幂等重试、40个输入工作集边界、沙盒/representation staging清理、交付重试和Secret不泄漏；不得以容器healthy替代业务证据。

#### Scenario: PDF总结并交付原件
- **WHEN** 合成用户上传合法PDF并要求总结后转发原件
- **THEN** 证据关联原附件、source Version、processing run、Markdown/JSON representation、Manifest v5、Working Set、沙盒Markdown读取、Agent结果和原PDF Delivery
- **AND** Agent沙盒、模型上下文和Delivery均未混淆原件与representation

#### Scenario: 扫描件OCR成功
- **WHEN** 合成扫描PDF或带文字图片在`docling-layout-ocr-v2`内完成OCR
- **THEN** Agent只通过Markdown读取提取文字并给出基于该文字与布局坐标的结果
- **AND** 系统不声称获得未提取的视觉语义

#### Scenario: 无文字图片拒绝模型调用
- **WHEN** 只有一张合法但OCR为NO_TEXT的图片
- **THEN** Job不调用模型并通过原reply route返回安全说明

#### Scenario: 无附件文字消息正常执行
- **WHEN** 合成用户只发送非空文字且不上传或引用文件
- **THEN** Job使用protocol 1.3和空schema v5文件上下文完成模型执行与文字Delivery
- **AND** 不出现旧Manifest投影或文件合同校验错误

#### Scenario: Docling重启恢复
- **WHEN** Docling在已返回task ID后重启并丢失临时任务
- **THEN** 同一processing run创建受控新attempt并最终成功或确定失败
- **AND** 不产生重复source Version或representation

#### Scenario: 文档处理Secret不泄漏
- **WHEN** 验收检查容器环境、MQ、Job、Tool事件、审计、API和日志
- **THEN** 不存在MinIO Secret、Docling API Key、Service bootstrap credential、原始正文、对象键或真实业务文件

#### Scenario: 旧合同不存在于发布产物
- **WHEN** CI检查后端、前端和Runtime发布产物
- **THEN** 不存在`text-v1`、`docling-text-v1`、`docling-layout-ocr-v1`、Manifest v1-v4或Runtime protocol 1.0-v1.2运行实现
- **AND** migration与变更文档中的删除说明不被误判为运行支持

## ADDED Requirements

### Requirement: 开放测试文件域重置必须显式且完整
平台 SHALL 提供一次性、显式确认的开放测试文件域重置命令。命令 MUST 先只读预检并拒绝任何非终态文件processing run、Agent Job、Delivery、Outbox或相关RabbitMQ消息，再通过File Service对象存储适配器删除受管文件对象，并按外键拓扑事务性删除旧附件正文、附件文件绑定、Workspace、Catalog、Working Set、Manifest、File/Version、Representation、processing、提交、保留、文件Delivery及其强关联终态测试事实。命令不得接受任意bucket、对象前缀、数据库表名或外部URL。

#### Scenario: 操作者未提供精确确认
- **WHEN** 操作者运行重置命令但未提供文档规定的精确环境标识和确认短语
- **THEN** 命令只输出脱敏预检摘要并退出
- **AND** 不删除数据库行或对象

#### Scenario: 仍有非终态执行或队列消息
- **WHEN** 预检发现RUNNING、PENDING、WAITING、RETRY、未终态Outbox/Delivery或相关队列积压
- **THEN** 重置失败关闭并输出按类别聚合的安全计数
- **AND** 不执行部分对象或数据库删除

#### Scenario: 开放测试文件域为空后重置完成
- **WHEN** 所有门禁通过且操作者提供精确确认
- **THEN** 命令删除受管对象与目标测试事实并执行数据库和对象存储空域核验
- **AND** 任一删除或核验失败都返回非零状态且不得宣称完成

### Requirement: 单一文件合同migration必须删除旧结构并拒绝遗留引用
一次性Migrator MUST 在文件域重置完成后执行前向migration，删除`attachment_content`、重复文件身份影子列、未使用的Job文档Profile字段、可切换文本策略字段及其旧约束，并把Profile、Manifest和Runtime执行摘要约束收缩到`NONE|docling-layout-ocr-v2`、schema v5和protocol 1.3。migration MUST 在任何旧Profile、旧Manifest、旧Runtime协议、活动部署或非终态引用仍存在时失败关闭，不得更新、投影或回填成当前合同。

#### Scenario: 旧测试数据未清空
- **WHEN** Migrator发现旧Manifest行、旧Profile引用、旧附件正文或旧协议执行摘要
- **THEN** migration整体回滚并提示先运行显式开放测试文件域重置
- **AND** 不保留半数新约束或半数旧列

#### Scenario: 重置完成后应用migration
- **WHEN** 预检确认只剩当前Profile引用且文件域与旧执行事实为空
- **THEN** migration在单事务中删除旧结构并安装唯一当前约束
- **AND** schema contract只声明当前列、表和允许值

### Requirement: 单一合同部署不得保留回退服务
部署编排 SHALL 一次性重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，并且不得并行运行包含旧Profile、旧Manifest或旧Runtime协议的镜像。入口恢复前 MUST 验证所有消费者、生产者、数据库约束和管理端bundle来自同一构建版本。

#### Scenario: 仍有旧Worker镜像消费队列
- **WHEN** 部署预检发现任一旧Agent Worker、File Worker、Processing Worker或Runtime实例仍注册或消费
- **THEN** 入口流量不得恢复
- **AND** 系统不依靠双写、版本协商或重试到旧服务维持运行
