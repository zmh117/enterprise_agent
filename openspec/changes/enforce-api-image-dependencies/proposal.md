## Why

现场 API 容器在加载业务应用请求模型时退出。项目使用 Pydantic v2 的集合约束、配置和序列化 API，根依赖清单却允许间接安装 Pydantic v1。当前镜像构建未执行 Uvicorn 对应的应用工厂，CI 的构建命令还引用了已经改名的 Runtime 服务。

## What Changes

- 声明平台直接使用的 Pydantic 和 Starlette，让安装附加依赖时也遵守平台依赖约束。
- API 镜像在交付前用管理端路由构造真实应用并生成 OpenAPI。
- 修复镜像 CI 的 Compose 服务选择，验证它实际覆盖现有构建目标。

## Capabilities

### Modified Capabilities

- `platform-operations`：平台 Python 依赖解析与 API 镜像构建验收。

## Impact

涉及后端项目依赖、后端镜像及其 CI。现场更新通过常规带构建的 Compose 部署生效。
