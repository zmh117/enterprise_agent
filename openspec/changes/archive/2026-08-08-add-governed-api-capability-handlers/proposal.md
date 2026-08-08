## Why

平台已有内部只读工具、Agent/Application 发布与外部身份基础，但尚不能由管理员安全地把受治理外部 API 配置成模型可调用能力，也不能保证钉钉消息始终使用当前发送人自己的 ONES 身份、默认 Team 和凭据执行。现在需要补齐一条不可变、可验证、可审计且失败关闭的发布链，并用 `cap__ones__work_item__search` 验证完整闭环。

## What Changes

- 新增统一的“API Capability 配置”工作台；界面整合 Capability、公开输入/输出 Schema、声明式 Handler、Mapping Plan 和测试预览，内部模型仍保持 Capability、Handler、API Connection、Authentication Profile 分离。
- 新增 API Connection 与 Authentication Profile 的 Draft、Verify、Publish 生命周期，以及首个 ONES Connection 的管理员临时自验证启动流程；只允许固定 Origin、相对路径和同 Origin 调用。HTTPS 为默认传输，企业内网或本地 ONES 使用 HTTP 时必须由管理员在 Connection Draft 中显式授权明文传输并接受安全警告。
- 扩展现有 ONES 外部身份管理为两阶段自助绑定：密码只用于一次登录验证，用户选择默认 Team 后原子保存身份、Team 集合与加密个人 Token；管理员只能治理他人绑定元数据。
- 新增 `cap__` 命名空间、稳定 Capability Identifier、Capability/Handler Revision、Capability Release，以及 `ACTIVE`、`DEPRECATED`、`DISABLED`、`ARCHIVED` 运维状态；发布配置不可变，可复制为新 Draft。
- 新增固定 `http-json-v1` 声明式执行器和受限 Mapping Plan，只支持确定性投影、数组逐项映射、固定默认值和基础标量转换；禁止任意代码、脚本、模板、完整 URL、动态主机和隐式 Handler 流水线。
- Agent Publication 冻结精确 Capability Release 上限，Application Publication 只能冻结该上限的显式子集；不新增逐用户或逐角色 Capability `use` Grant，也不新增全局功能开关。
- 钉钉运行时按实际发送人解析应用访问和 ONES 执行主体；Job 冻结 User ID/default Team 快照，每次外部调用前实时复核绑定、Team 与当前个人 Token，禁止主体或 Team 漂移。
- 模型可以依据公开 Schema，把一个 Capability 的规范化输出组织为另一个 Capability 的输入；平台不透传原始响应，也不建立服务端 Handler-to-Handler 管道。
- 新增查询型生产能力 `cap__ones__work_item__search`，固定为 `QUERY` 和 `INTERNAL`；同时提供测试专用双 Capability fixture 验证模型侧组合调用。
- 原始外部 HTTP 响应仅存在于单次尝试内存；持久化仅允许经过 Schema 和大小限制的规范化结果与安全元数据。按故障分类对查询请求最多重试两次，401 使凭据失效，其余失败关闭。

## Capabilities

### New Capabilities

- `governed-api-capability-control-plane`: 统一配置工作台、Capability/Handler/Mapping Draft、验证证据、并发控制、原子幂等发布和 Release 生命周期。
- `external-api-connection-authentication`: API Connection 与 Authentication Profile 的固定网络边界、版本生命周期、认证注入和首连接启动验证。
- `external-api-credential-binding`: 当前用户 ONES 两阶段绑定、默认 Team 选择、加密个人 Token、本人/管理员界面模式及凭据生命周期。
- `api-capability-publication-composition`: Agent Capability Envelope、Application Capability Allowlist、精确 Release 选择、显式升级和配置界面展示规则。
- `governed-api-capability-runtime`: Tool 暴露与执行复核、系统上下文注入、主体快照、Mapping 执行、重试、数据边界、审计及多 Capability 组合语义。
- `ones-work-item-search`: `cap__ones__work_item__search` 的公开契约、固定 ONES 查询、用户级 Team 范围和端到端验收。

### Modified Capabilities

- `agent-audit-permission`: 钉钉应用访问与外部 Capability 调用改为校验路由、启用用户、Agent/Application 冻结集合、Release 状态和个人凭据，并增加相应安全审计要求。
- `agent-job-lifecycle`: Job 创建时增加不可变外部执行主体快照，工具尝试和规范化结果按既有 Job/会话生命周期持久化。
- `claude-agent-runtime-integration`: 在保留内置写工具禁用的前提下，按发布快照暴露 `cap__*` Tool，并支持以不可信规范化结果组织后续 Tool 输入。
- `dingtalk-agent-ingress`: 钉钉消息命中活动 Application Publication 后，以每条消息实际发送人解析应用访问和外部执行主体，并为未绑定或停用用户返回安全提示。

## Impact

- 影响管理端 API、领域模型、数据库迁移、加密凭据存储、发布/解析读模型、Agent 与 Application 配置页、现有外部身份面板及普通用户“我的外部身份”入口。
- 影响 Agent Job 创建、Claude Tool 注册与执行、钉钉入口解析、外部 HTTP 客户端、重试策略、Tool Call/审计记录和安全错误分类。
- 影响 Connection Origin 的传输策略：生产环境不再无条件拒绝 HTTP，但未显式授权的 HTTP 仍失败关闭；该授权被冻结到不可变 Connection Revision，不代表完整网络区或 SSRF 防护。
- 与现有内部代码注册表 Handler 和只读 Tool 并存：`cap__` 专用于声明式受治理外部 API，既有 `mcp__internal__*`、未升级的 Agent/Application Publication 和历史发布行为保持不变。
- 第一版只落地一个逻辑 ONES Connection、每用户一个 ONES 账号和一个生产查询 Capability；多 ONES 实例、写操作、完整网络区/CIDR/DNS 出站治理、定时清理及记忆系统均不在本变更范围。
