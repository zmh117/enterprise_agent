## MODIFIED Requirements

### Requirement: 任务文件与浏览器证据的 MinIO 凭据隔离
Compose 和运行配置 MUST 只向 `file-service` 提供任务文件桶 endpoint 与受治理凭据引用。主 Compose SHALL 默认启动证据桶初始化、Loki 和 Alloy，复用 MinIO，由 Loki 使用独立身份访问私有证据桶。两个运行身份不得跨桶访问，证据桶独立配置容量和保留期。管理凭据只供 MinIO 与一次性存储初始化使用。Agent、Runtime、File Worker、Delivery Dispatcher、API、Alloy 和前端 MUST NOT 获取对象存储凭据。File Service 健康、错误和配置快照只显示 configured 状态与脱敏 endpoint 摘要。

#### Scenario: File Worker环境被检查
- **WHEN** 运维查看 `file-worker` 有效配置和容器挂载
- **THEN** 不存在 MinIO Secret 值或可解析 Secret usage

#### Scenario: MinIO Secret不可用
- **WHEN** File Service 引用的 Secret 缺失、禁用或无法解密
- **THEN** File Service readiness 失败且不回退到空值、旧 env Secret 或临时凭据

#### Scenario: 本地首次启动初始化受治理Secret
- **WHEN** 本地 Compose 显式启用文件存储 Secret bootstrap 且目标平台 Secret 尚不存在
- **THEN** 一次性 Migrator 从只读 Docker Secret 为文件桶身份创建 encrypted_db 加密版本后销毁自身运行态。它不获得 MinIO endpoint、桶或对象访问路径；生产部署可以关闭本地 bootstrap
- **AND** 不向长期运行服务暴露 bootstrap 值，重复启动保留相同值，值不同则失败而不自动轮换

#### Scenario: 文件与证据共享对象存储
- **WHEN** 执行普通 `docker compose up -d`
- **THEN** 文件服务与 Loki 均可读写自己的桶，交叉读取、写入与删除被拒绝，API 在内部网络用 HTTP 写入 Alloy、读回 Loki，Alloy 通过 HTTP 转发到 Loki，两个服务均不发布宿主端口

#### Scenario: 未设置证据专用身份时首次启动
- **WHEN** 已完成平台基础配置，部署没有额外提供证据存储身份或证书
- **THEN** 证据初始化为私有桶创建专用随机身份，Loki 可用该身份写入，后续启动复用该身份和原有数据
