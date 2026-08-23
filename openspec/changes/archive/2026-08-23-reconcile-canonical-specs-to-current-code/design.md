## Context

当前 10 个 canonical domain 是唯一规范基线，但其中八个领域仍保留了被后续实现取代的阶段性条款。冲突既包括同一文件内部的正反要求，也包括规范对不存在的 CLI、数据表、API 字段、Runtime 或认证方式作出的正向声明。

本 change 的证据优先级为：当前生产代码与显式 schema/常量，其次是 active migration 和 Compose manifest，再次是直接覆盖该合同的自动化测试。Archive、旧 proposal、旧 tasks、运行手册和 `__pycache__` 不作为当前能力存在的证据。没有直接反证的条款不因关键词搜索不到而删除。

## Goals / Non-Goals

**Goals:**

- 让 canonical Requirement 不再同时描述互斥行为。
- 删除当前没有代码、migration、API、CLI 或测试入口的正向能力声明。
- 保留历史数据兼容、失败关闭、Secret 隔离、授权、审计和不可变 Publication 等现行安全边界。
- 只改规范，并通过严格 OpenSpec 校验和相关现有测试证明事实依据没有漂移。

**Non-Goals:**

- 不实现被删除的身份重置、HMAC Webhook、动态 API Capability/Handler 或多 Runtime 能力。
- 不删除当前代码中的 Registry、Provider、Adapter、Manager 或兼容分支。
- 不改变数据库、Compose、API、前端或运行时行为。
- 不把缺少真实外部 ONES、DingTalk 或全链 E2E 证据写成已完成验收。

## Decisions

### 1. 只修正可由当前检出直接证明的冲突

采用代码常量、请求 schema、固定目录、Compose 渲染结果和测试断言建立事实清单。例如 `SUPPORTED_RUNTIME_KINDS={python-v1}`、Agent 创建请求的 `Literal["python-v1"]`、`OnesToolRegistry` 的两个 Tool、Webhook 对 HMAC 的显式拒绝、Business Application 的 `mcp_tools` 字段和 `admin-web` 的入口 guard。

未采用“规范标题在代码中搜不到就删除”的方案，因为业务语义通常不会以相同中文标题出现在实现中，容易误删安全合同。

### 2. 当前产品合同覆盖已完成或未实现的迁移计划

身份与授权全量重置没有对应 CLI、表、服务或测试；它保持在历史 archive 中，但从 canonical 删除。TypeScript Runtime 的退役流程已经不再有源码 CLI，因此 canonical 只保留当前 Python-only 执行和历史 TypeScript 事实只读合同，不再要求一个不存在的退役命令。

未采用为缺失能力补代码的方案，因为用户要求以代码事实修正规范，且本 change 明确不新增功能。

### 3. 用当前稳定边界替换旧对象名称

旧 API Capability/Handler/Connection/Release 正向合同统一收敛为代码 Manifest 的 MCP Tool、固定 MCP Server policy 和代码拥有的 ONES GraphQL/REST Operation。历史对象只在拒绝旧字段或禁止回归的负向场景中保留。

### 4. 凭据事实以加密持久化实现为准

ONES Challenge 会短期保存用途绑定的加密登录材料与 Token；确认后会创建或更新加密 `external_identity_credential`，并在本人/治理投影中展示安全状态和 revision。规范必须明确“不得保存明文或返回密文”，而不是声称凭据根本不存在。

### 5. Compose 合同描述实际失败关闭，而非不存在的 profile

当前 `docker-compose.yml` 默认包含 `admin-web`，但 `FEATURE_WEB_ADMIN=false` 时容器入口脚本非零退出并不提供页面。因此规范描述实际 guard，不声称当前存在已注释掉的 admin profile。

## Risks / Trade-offs

- [风险] 删除未实现计划后，未来开发者误以为该能力从未讨论过。→ 历史 proposal/design/tasks 保留在 archive，仅从默认 canonical 读取路径移除。
- [风险] 规范对当前实现绑定更紧，后续实现变更需要同步更新。→ 这是 canonical 作为当前已接受合同的预期成本；未来行为变化必须创建新 change。
- [风险] 仅做静态与自动化验证不能证明真实外部环境。→ 验证报告明确区分代码事实、Compose manifest 和未执行的真实外部 E2E。
- [风险] 大量删除可能误触仍有实现的边界。→ 删除项限定为具有明确反证的 Requirement，并保留通用授权、审计、Secret 和历史只读要求。

## Migration Plan

1. 为八个受影响领域创建 delta spec。
2. 严格验证 active change。
3. 按 delta 智能合并到 canonical spec，不改变未列出的 Requirement。
4. 运行相关现有测试、10 个 canonical strict validation、Compose config 和 `git diff --check`。
5. 将 tasks 全部完成后归档该 change；archive 不参与默认规范解析。

本 change 无运行部署、数据库迁移或回滚步骤。规范回滚仅需反向恢复本 change 对 canonical 的文档 diff；不应改动 archive 历史。

## Open Questions

无。未完成的真实 ONES 目标环境验证和完整 Runtime→Delivery E2E 继续作为历史验收缺口，不在本 change 中伪造完成状态。
