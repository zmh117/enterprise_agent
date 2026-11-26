## MODIFIED Requirements

### Requirement: File Service 是唯一文件事实入口
系统 MUST 由 `file-service` 统一管理任务工作区、文件、文件版本、配额、生命周期、审计和对象位置，并 SHALL 同时暴露受治理 File MCP 接口与受控内部 API。只有 File Service 基础设施层可以解析任务文件的 MinIO Secret Reference 并操作任务文件桶；Agent、Runtime、`file-worker`、MCP 参数或响应、Job、日志和审计 MUST NOT 接收 MinIO Access Key、Secret Key、Session Token、Bucket 或对象键。

#### Scenario: Agent 通过 File MCP 操作文件
- **WHEN** RUNNING Job 调用已冻结且授权的文件工具
- **THEN** File Service 根据 Job 解析任务工作区和受控对象位置并完成操作
- **AND** Agent 与 Runtime 不获得 MinIO 凭据或任意对象键

#### Scenario: Worker 尝试直接操作 MinIO
- **WHEN** `file-worker` 请求导入附件或清理到期内容
- **THEN** 它必须调用 File Service 内部 API
- **AND** 部署不得向 `file-worker` 注入 MinIO 凭据

#### Scenario: 浏览器证据保留期清理
- **WHEN** Loki 在共享 MinIO 上清理到期证据
- **THEN** 其身份只能删除专用证据桶的对象，无法读取或删除任务文件
