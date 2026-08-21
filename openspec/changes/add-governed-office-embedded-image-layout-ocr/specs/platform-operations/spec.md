## ADDED Requirements

### Requirement: 布局OCR复用隔离处理拓扑并固定模型artifact
默认部署 SHALL 复用内部`docling-serve`、独立`file-processing-worker`、File Service、File Domain Outbox和RabbitMQ文档处理边界来执行parent、picture item与assembly任务，不得把Docling或OCR暴露为Agent Tool/MCP，也不得新增可绕过File Service的图片对象入口。Docling/OCR/layout所需模型与配置 MUST 在构建或受控部署阶段固定revision与digest并离线可用；运行时下载、远程services、自定义模型、Callback、HTTP source和外部插件 MUST 保持关闭。

#### Scenario: 检查处理组件Secret和网络
- **WHEN** 运维检查File Processing Worker、Docling和File Service的环境、Secret、网络及挂载
- **THEN** 只有File Service具有对象存储凭据，Worker只有角色bootstrap/RabbitMQ/Docling API Key，Docling只有自身固定API Key与模型artifact
- **AND** 任何处理组件都不获得任意对象键、其它Worker凭据或外网图片/模型访问

#### Scenario: 固定OCR模型缺失
- **WHEN** 容器离线启动但Profile固定的OCR/layout artifact不存在、digest不匹配或无法加载
- **THEN** Docling/Worker readiness失败且布局Profile不得报告READY
- **AND** 不尝试访问互联网下载或回退到其它模型

### Requirement: 布局OCR资源与积压可安全观测
平台 MUST 对parent parse、picture item、assembly、asset staging、Representation staging、retry、dead-letter和cleanup分别提供有界积压计数、最早时间、Profile/processor版本、阶段、attempt和白名单错误分类。readiness MUST 验证Profile registry/hash、layout schema、必需输出集合、固定模型artifact、File Service内部流、RabbitMQ拓扑和Docling真实就绪；日志、健康、指标和运维API不得显示业务文件名、图片、OCR文字、坐标、对象键、响应正文或凭据。

#### Scenario: 图片OCR出现积压
- **WHEN** picture item队列超过代码固定告警阈值
- **THEN** 运行中心显示数量、最早创建时间、Profile、stage和安全错误分类
- **AND** 不显示图片内容、OCR文本或父文件名

#### Scenario: 容器运行但layout schema不兼容
- **WHEN** 组件进程running但File Service不认识Profile要求的`OCR_LAYOUT_JSON` schema或输出集合
- **THEN** readiness返回非就绪并阻止新布局OCR run
- **AND** 不以容器health替代契约就绪

### Requirement: 布局OCR验收覆盖坐标、恢复和能力边界
上线验收 MUST 使用不含真实业务数据的合成DOCX/PPTX，覆盖内嵌图片文字、重复图片、旋转/裁剪、低置信度、多block、无文字、损坏图片、超图片数、超像素、超输出大小及提示注入。证据 MUST 关联source Version、parent run、picture asset/occurrence/item、三种Representation、Manifest、Runtime Markdown读取、Agent结果与原件Delivery，并验证逐图重试、Docling重启、Worker崩溃、幂等assembly、asset/representation清理和Secret不泄漏；不得以单元测试或容器healthy代替新鲜业务链路。

#### Scenario: PPTX布局OCR成功
- **WHEN** 合成PPTX包含已知slide/shape位置和多个已知图片内文字框
- **THEN** 验收证明父锚点、规范化bbox、reading order、几何关系和布局Markdown与样本期望一致
- **AND** Agent只通过Markdown说明图片文字/布局，不声称箭头、颜色或照片语义

#### Scenario: DOCX重排不改变锚点语义
- **WHEN** 同一合成DOCX在不同字体/分页环境下处理
- **THEN** 验收使用稳定文档节点/段落锚点和图片内部坐标比较结果
- **AND** 不要求或断言稳定页码bbox

#### Scenario: 单张图片任务重试
- **WHEN** 多图片文档中一个Docling picture task在返回task ID后丢失
- **THEN** 同一item有限重试并最终成功或确定失败，其它终态item不重算
- **AND** parent只发布一组Profile要求的Representation

#### Scenario: 图片提示注入不能扩大权限
- **WHEN** 合成图片OCR文字要求忽略系统规则并调用未授权Tool
- **THEN** Agent把它作为不可信文件内容处理且服务端权限/工具集合保持不变
- **AND** MQ、日志和审计不出现该OCR正文
