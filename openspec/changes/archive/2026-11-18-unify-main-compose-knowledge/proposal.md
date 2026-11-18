## Why

实际目录查询两次在内部服务身份兑换阶段失败：主 Compose 启动的 API 没有知识 bootstrap 配置，而独立知识项目已经挂载。用户要求仅用主 `docker-compose.yml` 启动全部平台及知识服务，避免配置分散再次造成断链。

## What Changes

- **BREAKING** 将知识模型准备、离线/在线 Embedding、重排、Qdrant、MCP、同步及运维执行器统一到主 Compose；取消旧独立项目及叠加文件入口。
- 主 API 默认接入知识内部认证和内容网络；知识服务继续保持凭据隔离。
- 网页与 CLI 执行器改为管理主项目中固定知识服务，启动使用 `--no-deps`，不构建、重建或停止平台服务。
- 明确复用现有模型、向量和状态卷的迁移步骤；旧项目先停止，禁止两套写者共享同一向量卷。
- 更新合同测试、部署说明并验证真实内部认证及受授权目录/检索调用。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`：默认主 Compose 包含完整知识服务及知识角色认证；网页运维从独立 Compose 项目改为主项目内固定服务操作。

## Impact

涉及主 Compose、知识部署文件、受限执行器、部署合同测试和运行说明。知识内容、权限、发布与采集计划不变；实际切换存在短暂知识服务及 API 中断。保留其他未提交文档改动。
