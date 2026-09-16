## ADDED Requirements

### Requirement: 部署必须注入可比较的组件构建身份
平台 SHALL 为Control Plane、Agent Worker、Python Runtime和File Service注入有界安全构建身份，至少包含固定组件名、源码`source_revision`、发布`build_id`和标准OS/architecture `platform`；部署系统能够准确取得实际镜像摘要时还 SHALL提供`image_digest`。`source_revision`与`build_id` MUST由构建流水线和发布清单产生且不可由Agent、Application、外部请求、模型输出或Job payload覆盖。服务不得挂载Docker socket、查询容器daemon或把可变tag伪装成digest来补全身份。

必需身份缺失或格式无效时，相关服务readiness MUST失败。Control Plane SHALL在Job创建事实中关联自身身份，Worker SHALL在protocol 1.4 invocation事实中关联自身身份，Runtime SHALL在安全事件中声明自身身份，File Service SHALL在已认证MCP初始化元数据中声明自身身份；运行记录只展示这些安全字段，不展示registry凭据、环境变量或原始容器配置。

#### Scenario: 同一发布的组件身份一致
- **WHEN** 部署预检比较API、Agent Worker、Python Runtime和File Service
- **THEN** 各组件`source_revision`和`build_id`符合当前不可变发布清单
- **AND** 任一组件缺失、格式无效或引用另一发布时入口不得恢复

#### Scenario: 部署无法取得镜像digest
- **WHEN** 某本地Compose环境无法准确向容器注入实际镜像digest
- **THEN** 组件明确报告该可选字段未观测，同时仍报告必需revision、build ID和platform
- **AND** 系统不得使用镜像tag、容器ID或猜测值冒充digest

#### Scenario: 跨架构镜像摘要不同
- **WHEN** Mac arm64与Windows或Linux amd64由同一源码revision和build ID构建且工具契约hash一致，但平台与镜像digest不同
- **THEN** 系统把不同digest保留为各自产物证据而不单独判为工具契约漂移
- **AND** 操作者仍可使用platform和digest定位两端实际运行产物

## MODIFIED Requirements

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT、LOG、Markdown、born-digital PDF、扫描PDF、DOCX、PPTX、XLSX、带文字图片和无文字图片及假凭据，证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、File Domain Outbox、processing RabbitMQ拓扑、File Processing Worker、Docling、Agent Worker、Python Runtime protocol 1.4、Job Sandbox、File MCP live对账、Runtime effective registry、Prompt contract、原件Delivery和文本结果形成新鲜链路。验收还 MUST 覆盖无附件文字Job、Principal/API Key拒绝、越权文件、MIME伪装、加密/损坏/超大小/超页数、PARTIAL、NO_TEXT、Markdown超限、Docling重启、结果取得后Worker崩溃、幂等重试、40个输入工作集边界、沙盒/representation staging清理、交付重试、工具契约失败关闭和Secret不泄漏；不得以容器healthy替代业务证据。

#### Scenario: PDF总结并交付原件
- **WHEN** 合成用户上传合法PDF并要求总结后转发原件
- **THEN** 证据关联原附件、source Version、processing run、Markdown/JSON representation、Manifest v5、Working Set、沙盒Markdown读取、工具契约观测、Agent结果和原PDF Delivery
- **AND** Agent沙盒、模型上下文和Delivery均未混淆原件与representation

#### Scenario: 扫描件OCR成功
- **WHEN** 合成扫描PDF或带文字图片在`docling-layout-ocr-v2`内完成OCR
- **THEN** Agent只通过Markdown读取提取文字并给出基于该文字与布局坐标的结果
- **AND** 系统不声称获得未提取的视觉语义

#### Scenario: 无文字图片拒绝模型调用
- **WHEN** 只有一张合法但OCR为NO_TEXT的图片
- **THEN** Job不调用模型并通过原reply route返回安全说明

#### Scenario: Docling重启恢复
- **WHEN** Docling在已返回task ID后重启并丢失临时任务
- **THEN** 同一processing run创建受控新attempt并最终成功或确定失败
- **AND** 不产生重复source Version或representation

#### Scenario: 文档处理Secret不泄漏
- **WHEN** 验收检查容器环境、MQ、Job、Tool事件、工具契约观测、审计、API和日志
- **THEN** 不存在MinIO Secret、Docling API Key、Service bootstrap credential、Principal JWT、完整Prompt、完整Tool Schema、原始正文、对象键或真实业务文件

#### Scenario: 无附件文字消息正常执行
- **WHEN** 合成用户只发送非空文字且不上传或引用文件
- **THEN** Job使用protocol 1.4和空schema v5文件上下文完成模型执行与文字Delivery
- **AND** 工具契约观测明确区分适用的Runtime effective事实与未绑定的File MCP观测

#### Scenario: File MCP缺少冻结提交工具
- **WHEN** 受控验收替身使Job冻结`file_create_commit_intent`但File MCP `tools/list`不声明该工具
- **THEN** Runtime在模型调用前产生`DRIFT`观测并以稳定错误失败关闭
- **AND** 运行记录详情显示`MISSING_REMOTE`且不依赖模型文字回答

#### Scenario: Runtime派生工具不被误报
- **WHEN** 匹配的File MCP与Job Snapshot使Runtime按规则注册`select_sandbox_output`
- **THEN** 运行记录把它显示为`runtime_derived`并关联`file_create_commit_intent`授权前提
- **AND** 不要求File MCP `tools/list`声明该派生工具

#### Scenario: 旧合同不存在于发布产物
- **WHEN** CI检查后端、前端和Runtime发布产物
- **THEN** 不存在`text-v1`、`docling-text-v1`、`docling-layout-ocr-v1`、Manifest v1-v4或Runtime protocol 1.0-v1.3可执行实现
- **AND** 历史只读Schema、migration与变更文档中的旧版本说明不被误判为运行支持

### Requirement: 单一文件合同migration必须删除旧结构并拒绝遗留引用
一次性Migrator MUST 在文件域重置完成后执行前向migration，删除`attachment_content`、重复文件身份影子列、未使用的Job文档Profile字段、可切换文本策略字段及其旧约束，并把当前可执行Profile、Manifest和Runtime执行约束收缩到`NONE|docling-layout-ocr-v2`、schema v5和protocol 1.4。migration MUST 在任何旧Profile、旧Manifest、protocol 1.0至1.3非终态执行、旧活动部署或非终态引用仍存在时失败关闭，不得把旧事实更新、投影或回填成当前合同。已经终态的protocol 1.3 Job和安全事件 SHALL作为只读历史保留，并明确排除在恢复和当前执行资格之外。

#### Scenario: 旧测试数据或非终态调用未清空
- **WHEN** Migrator发现旧Manifest行、旧Profile引用、旧附件正文或protocol 1.0至1.3非终态执行事实
- **THEN** migration整体回滚并提示先完成显式重置、排空或取消
- **AND** 不保留半数新约束、半数旧列或双协议消费者

#### Scenario: 保留protocol 1.3终态审计事实
- **WHEN** migration发现已经终态且满足安全事件约束的protocol 1.3 Job
- **THEN** 该事实保持不可变并只可通过历史投影读取
- **AND** migration不把它升级成1.4、不补造工具契约观测且不提供恢复入口

#### Scenario: 预检通过后应用migration
- **WHEN** 预检确认只剩当前Profile引用、schema v5文件事实且不存在旧协议非终态执行
- **THEN** migration在单事务中删除旧结构并安装唯一当前执行约束
- **AND** schema contract明确区分protocol 1.4活动事实与protocol 1.3终态只读历史

### Requirement: 单一合同部署不得保留回退服务
部署编排 SHALL 一次性重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，并且不得并行运行包含旧Profile、旧Manifest或Runtime protocol 1.0至1.3可执行实现的镜像。入口恢复前 MUST 验证所有消费者、生产者、数据库约束和管理端bundle符合同一不可变发布清单，相关服务报告预期`source_revision`、`build_id`和platform，Python Runtime health只声明protocol 1.4；实际镜像digest可按平台分别记录但不得缺失时伪造。

#### Scenario: 仍有旧Worker镜像消费队列
- **WHEN** 部署预检发现任一旧Agent Worker、File Worker、Processing Worker或Runtime实例仍注册或消费
- **THEN** 入口流量不得恢复
- **AND** 系统不依靠双写、版本协商或重试到旧服务维持运行

#### Scenario: 组件来自不同发布
- **WHEN** API、Agent Worker、Python Runtime或File Service报告的revision/build ID不符合本次发布清单
- **THEN** 部署预检失败并按组件输出安全差异
- **AND** 容器healthy或工具名称偶然相同均不得替代发布一致性证据

#### Scenario: protocol 1.4入口恢复
- **WHEN** 所有旧消费者已停止、非终态1.3事实为零、migration成功且新鲜合同与E2E通过
- **THEN** 平台只恢复protocol 1.4入口和消费者
- **AND** 入口恢复后不回退到protocol 1.3或恢复旧Job执行
