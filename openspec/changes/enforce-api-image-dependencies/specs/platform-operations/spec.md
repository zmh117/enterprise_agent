## ADDED Requirements

### Requirement: 平台 API 镜像在构建时验证 Python 依赖与请求模型

平台 Python 安装清单 MUST 显式要求兼容的 Pydantic v2。后端镜像安装附加依赖时 SHALL 遵守基础依赖约束。API 镜像 MUST 在构建时离线装配带管理路由的生产应用并生成 OpenAPI。镜像 CI SHALL 通过主 Compose 中的有效服务选择构建目标。

#### Scenario: 构建环境只能提供不兼容的依赖

- **WHEN** 软件源或附加依赖仅允许安装 Pydantic v1
- **THEN** 平台依赖解析失败，构建不会交付该镜像

#### Scenario: 管理路由或请求模型不能装配

- **WHEN** 在镜像内调用应用工厂或生成管理端 OpenAPI 失败
- **THEN** 构建失败，无需真实凭据、数据库或消息队列即可发现该错误

#### Scenario: CI 构建后端运行镜像

- **WHEN** 运行镜像 CI 的构建命令
- **THEN** API 与 Python Runtime 等已声明的目标均映射到当前 Compose 服务
