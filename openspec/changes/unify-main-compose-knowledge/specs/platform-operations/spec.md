## ADDED Requirements

### Requirement: 主 Compose 必须默认启动完整知识服务
根 `docker-compose.yml` SHALL 作为唯一常规部署入口，默认启动知识 Qdrant、离线及在线 Embedding、重排、MCP、受管同步和运维执行器。模型准备 SHALL 作为有界的一次性依赖，检索和同步 MUST 等待对应模型及平台 schema 就绪。API MUST 同时具备知识角色 bootstrap 配置和内容网络，不得依赖额外叠加文件才能启用内部知识接口。向量、模型及进度卷 MUST 使用稳定且可显式指定的名称；旧项目迁移 MUST 先停止旧写者，不得以新建空卷替代已有知识。

#### Scenario: 仅使用主文件启动
- **WHEN** 操作者准备部署配置与 Secret 后执行 `docker compose -f docker-compose.yml up -d --build`
- **THEN** 全部知识常驻服务随平台启动，内部服务身份兑换可用，不需要额外 Compose 文件或知识 profile

#### Scenario: 已有知识项目迁移
- **WHEN** 将同机旧知识项目迁移到主项目
- **THEN** 先核对并复用既有模型、向量和状态卷，旧同步及 Qdrant 写者停止后才启动新写者，知识权限及采集计划不变

#### Scenario: 网页单独启动知识服务
- **WHEN** 执行器执行网页知识启动操作
- **THEN** 只操作固定知识服务且不递归启动或重建平台依赖，平台依赖不就绪时预检失败

## MODIFIED Requirements

### Requirement: 知识库网页运维必须通过独立受限执行器
系统 SHALL 提供主 Compose 项目内知识服务 的构建、启动、停止、状态和日志入口。主程序侧常驻执行器 MUST 仅执行固定主项目中的知识服务的允许操作；普通 API 不持有 Docker socket，网页不得传任意命令、源码路径、Compose 文件或凭据。知识服务启动 MUST 显式限定服务并禁用依赖递归，不得重建 API、数据库、Migrator 或执行器自身。停止 MUST 保留数据卷、模型、同步进度及控制入口；构建 MUST 不隐式应用版本或触发采集。

#### Scenario: 停止后再启动
- **WHEN** 管理员停止整套知识库服务
- **THEN** 同步先保存断点，知识服务有序停止，主程序与执行器继续运行，管理员可以再次从网页启动

#### Scenario: 请求绕过操作边界
- **WHEN** 请求未获管理权限、缺少 CSRF 或带任意命令/路径/多余参数
- **THEN** 系统拒绝请求，不执行 Docker 操作

### Requirement: Compose完整配置Service Principal签发与刷新链路
默认Compose MUST 只维护一套平台Principal签名私钥和公开JWKS：现有平台API身份模块与Agent Worker只在需要签发对应Token时挂载同一私钥，File Service、ONES MCP及后续MCP只挂载同一公开`PRINCIPAL_JWKS`；不得声明或挂载第二套Service Principal私钥/JWKS。平台API还 MUST 挂载角色隔离的File Worker、File Processing Worker、Delivery Worker和Knowledge MCP bootstrap credential，并让每个Worker及Knowledge MCP只挂载自己的bootstrap credential。部署 MUST 使用按需签发和到期前刷新，不得要求宿主机预先提供短时Service JWT文件。密钥初始化 MUST 幂等生成统一Principal密钥/JWKS与全部bootstrap材料、拒绝不完整统一密钥组并保持私钥和bootstrap文件owner-only。Docling API Key MUST 与平台Principal体系分离，只挂载到`file-processing-worker`和`docling-serve`。
#### Scenario: 新环境首次启动
- **WHEN** 运维运行受控密钥初始化后启动默认Compose
- **THEN** 统一Principal密钥/JWKS及File Worker、File Processing Worker、Delivery Worker、Knowledge MCP bootstrap bind source均存在且容器可创建
- **AND** 三个Worker与Knowledge MCP能分别从平台身份接口取得可验证的角色JWT
#### Scenario: 检查角色Secret挂载
- **WHEN** 运维检查API、File Service、三个Worker与Docling的Compose Secret
- **THEN** API拥有统一Principal签名私钥和四份角色bootstrap credential，File Service只有统一公开JWKS
- **AND** 每个Worker只有自己的bootstrap credential，Docling API Key只在Processing Worker与Docling出现，任何组件都没有另一角色Secret
#### Scenario: 短时JWT到期
- **WHEN** 已缓存Service JWT进入刷新窗口或过期
- **THEN** Worker通过固定平台身份地址换取新JWT并继续调用
- **AND** 不回退到静态JWT、共享Token或未认证内部请求
#### Scenario: Docling API Key缺失
- **WHEN** `file-processing-worker`或`docling-serve`无法解析独立API Key
- **THEN** 对应readiness失败且不回退到无认证Docling请求
