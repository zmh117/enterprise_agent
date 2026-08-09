## ADDED Requirements

### Requirement: 旧平台必须在维护窗口彻底停止
系统 MUST 在破坏性清理前停止 Web/渠道新入口、Agent Worker、API Capability Runtime 和 Internal API Platform，并 MUST 拒绝创建新 Job；清理期间不得保留可接收旧 Tool 请求的旁路进程。

#### Scenario: 维护窗口仍有旧 Worker 运行
- **WHEN** 清理检查发现 Worker 或 Internal API Platform 仍能接收消息
- **THEN** 数据删除不得开始，运维必须先停止进程和入口

### Requirement: API Capability 控制面与运行数据必须直接删除
系统 MUST 删除 API Capability、Handler、Connection、Authentication Profile、Mapping Plan、Release、Publication 组合、HTTP attempt、Capability provenance 以及只服务这些对象的审计和历史数据；本变更 MUST NOT 为这些数据生成备份、导出、转换或兼容读取。

#### Scenario: 执行破坏性 schema 清理
- **WHEN** 维护窗口确认旧进程全部停止
- **THEN** 数据库迁移直接删除旧表、列、外键和数据，删除后旧 Capability 历史不可查询且不可恢复

### Requirement: Internal API Platform 代码与专属数据必须直接删除
系统 MUST 删除 Internal API Platform 服务、路由、客户端、配置、Resource 组合、Runtime Snapshot、旧协议 Tool 数据和 Compose wiring；数据库、Redis 和 Loki MUST 通过新声明式文件和 `platformctl` 从空状态重新配置，不得迁移旧资源记录。

#### Scenario: 新 Data MCP 首次启动
- **WHEN** 旧 Internal API Platform 数据已清理且 Data MCP 尚未配置资源
- **THEN** Data MCP 对资源依赖 Tool 失败为未配置，管理员通过 CLI 创建并验证新 Resource 后才可调用

### Requirement: 依赖旧平台的 Job 与 Tool 历史允许删除
系统 MAY 删除依赖旧 Capability/Internal Platform 的非终态与终态 Job、Step、Tool Call、attempt、result、delivery 关联和专属审计数据，并 MUST 清理阻止 schema 删除的交叉外键；系统 MUST NOT 尝试把这些 Job 物化为 MCP Job 或保留旧历史投影。

#### Scenario: 非终态旧 Job 存在
- **WHEN** 维护窗口发现排队、运行中或可重试 Job 引用旧 Runtime
- **THEN** 系统停止执行并删除该 Job及专属依赖数据，不迁移、不重试、不隔离保存

### Requirement: 保留数据必须限定为新系统仍需基础事实
清理 MUST 保留 `app_user`、系统密码 Hash、Session、钉钉/ONES 稳定外部身份、ONES 默认 Team 元数据、钉钉接入以及通用 Ingress/Outbox/Delivery 基础结构；清理 MUST 删除旧 `external_api_credential`、旧 Challenge 和只被旧模块引用的 Secret、Application Capability 组合、Resource 与审计，并 MUST 将保留的 ONES 身份标记为 `REVERIFICATION_REQUIRED`。

#### Scenario: 删除旧 Capability 数据
- **WHEN** ONES 身份仍存在且个人 Token 保存在依赖旧 Connection Revision 的凭据中
- **THEN** 清理保留稳定身份和默认 Team 元数据，删除旧 Token 凭据，不复制密文，并要求用户本人重新验证后创建新 Provider Credential

### Requirement: 旧代码、前端和部署入口必须同步移除
破坏性 schema 清理 MUST 与删除 API Capability/Internal API Platform 后端模块、管理 API、前端页面、Compose 服务、环境变量、依赖和测试同步完成；仓库与运行部署 MUST 不存在重新启用旧执行路径的配置开关。

#### Scenario: 清理后扫描旧入口
- **WHEN** 执行静态路由、依赖、Compose 和前端导航扫描
- **THEN** 不存在旧 Capability/Internal Platform 可调用入口或悬空引用

### Requirement: 删除后只允许新系统冷启动
删除完成后系统 MUST 运行新 migration/seed，通过 CLI 从空状态创建必要 Secret、Resource 与 Deployment，并在新链路验收通过后恢复入口；旧历史为空 MUST 被视为预期结果。

#### Scenario: 新 MCP 链路验收失败
- **WHEN** 数据已删除但 ONES MCP 或 Data MCP 验收失败
- **THEN** 系统保持入口关闭并继续修复或重新初始化新系统，不尝试恢复旧数据

### Requirement: 破坏性删除不提供数据级回滚
系统和运维文档 MUST 明确步骤执行后旧 API/Internal Platform 数据不可恢复；不得生成自动 rollback migration 来重建旧业务数据，也不得把空表重建描述为数据恢复。

#### Scenario: 删除后请求恢复旧历史
- **WHEN** 操作人尝试查询或恢复旧 Capability Job、Tool Call 或 Resource Snapshot
- **THEN** 系统明确返回数据已按变更范围删除，不伪造空记录或从新 MCP 数据反推旧历史
