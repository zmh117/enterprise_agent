## MODIFIED Requirements

### Requirement: Docling服务固定版本并保持内部隔离
默认Compose MUST 使用固定tag与多架构OCI index digest的官方`docling-serve`镜像，并由代码发布合同同时固定每个受支持平台的子manifest digest；部署现场不得通过环境变量或override替换模型artifact期望摘要。服务 MUST 禁用UI、远程services、HTTP URL source、Callback、自定义VLM/图片描述配置和外部插件；服务不得映射宿主端口，只能由`file-processing-worker`通过专用内部网络和独立API Key访问。容器 MUST 使用非root、只读根文件系统、受控scratch、CPU、内存、PID和时间限制，并在运行前准备所需模型artifacts而不是运行时访问互联网。

#### Scenario: 检查Docling Compose配置
- **WHEN** 运维渲染默认Compose配置
- **THEN** `docling-serve`使用固定OCI index digest、发布合同包含当前平台对应的固定子manifest、无宿主端口、UI关闭且远程/自定义能力关闭
- **AND** 不存在PostgreSQL、RabbitMQ、MinIO、平台Principal Secret或`DOCLING_MODEL_ARTIFACT_DIGEST`部署覆盖

#### Scenario: Docling模型尚未就绪
- **WHEN** `/health`成功但`/ready`因模型加载、artifact校验或内部编排器失败返回非就绪
- **THEN** 平台文档处理状态不得报告READY
- **AND** processing worker不得把请求发送到未就绪实例

#### Scenario: OCI index的平台成员不符合发布合同
- **WHEN** 发布校验发现固定index解析出的AMD64或ARM64子manifest与代码发布映射不一致
- **THEN** 镜像发布和部署失败
- **AND** 不通过修改环境变量、采用本地缓存镜像或忽略平台差异继续启动

### Requirement: 布局OCR复用隔离处理拓扑并固定模型artifact
默认部署 SHALL 复用内部`docling-serve`、独立`file-processing-worker`、File Service、File Domain Outbox和RabbitMQ文档处理边界来执行parent、picture item与assembly任务，不得把Docling或OCR暴露为Agent Tool/MCP，也不得新增可绕过File Service的图片对象入口。Docling/OCR/layout所需模型与配置 MUST 在构建或受控部署阶段固定revision、摘要算法、多架构OCI index以及每个受支持平台的子manifest和模型artifact digest并离线可用；完整平台映射 MUST 属于Profile canonical payload，运行时实算仅用于校验所选平台条目且不得反向成为配置。运行时下载、远程services、自定义模型、Callback、HTTP source和外部插件 MUST 保持关闭。

#### Scenario: 检查处理组件Secret和网络
- **WHEN** 运维检查File Processing Worker、Docling和File Service的环境、Secret、网络及挂载
- **THEN** 只有File Service具有对象存储凭据，Worker只有角色bootstrap/RabbitMQ/Docling API Key，Docling只有自身固定API Key与代码发布的模型artifact映射
- **AND** 任何处理组件都不获得任意对象键、其它Worker凭据或外网图片/模型访问

#### Scenario: 固定OCR模型缺失
- **WHEN** 容器离线启动但Profile为当前平台固定的OCR/layout artifact不存在、digest不匹配或无法加载
- **THEN** Docling/Worker readiness失败且布局Profile不得报告READY
- **AND** 不尝试访问互联网下载、采用现场实算值或回退到其它平台/模型

#### Scenario: 两个平台验证同一发布合同
- **WHEN** 发布流程分别验证`linux/amd64`和`linux/arm64`镜像
- **THEN** 每个平台的实际模型目录摘要与完整Profile映射中对应条目一致，且两端Profile hash相同
- **AND** 只有升级固定OCI index或模型内容的代码变更才可更新映射并产生新的Profile hash
