## Why

用户明确要求把本机知识库 Qdrant 从 1.17.0 升级到 v1.19.1 并固定版本。现有向量卷已包含正式索引，必须保留恢复点、遵循中间次版本升级路径，并用实际运行验证交付，而非仅修改镜像标签。

## What Changes

- 为单节点 Qdrant 创建一致性备份，在隔离副本验证逐版本升级后，仅升级知识库 Qdrant 服务。
- 将 `knowledge/compose.yml` 固定到 `qdrant/qdrant:v1.19.1@sha256:...` 的实际核验摘要，不使用浮动 latest。
- 验证版本、集合配置、全部点身份/向量摘要、实际检索及重启恢复；补部署合同测试、运行手册和脱敏升级证据。
- 不重启 PostgreSQL、Embedding 或业务服务，不执行数据库迁移、重新向量化、权限发布、MCP 接入或删除既有数据卷。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `platform-operations`：明确知识向量数据库的固定镜像、连续次版本升级、恢复点及实际数据验收边界。

## Impact

仅涉及可选知识 Compose、现有部署合同测试、运行手册与本机 Qdrant 容器和任务专用备份/演练卷。保留其他并行工作，不提交、不推送、不归档。用户已明确批准本次版本升级及固定，其他服务或数据操作不在授权范围内。

## 2026-09-18 后续授权

用户随后要求“更新镜像重启服务”。本次后续范围为按当前代码重建 `knowledge-ops`，消除其 catalog 落后于数据库的门禁失败；定向重启 Qdrant/Embedding 两个知识常驻服务并用默认运维镜像只读验收。`knowledge-ops` 是一次性任务，重新运行而非常驻启动。不升级模型、不执行迁移或重新索引、不重启 PostgreSQL/业务主栈，不删除恢复点。
