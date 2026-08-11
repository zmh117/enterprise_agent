# Enterprise Agent 协作约束

## 工作方式

- 需求不清时，不准直接执行；必须先向用户确认规格。
- 不要默认最小改动，默认选择稳健方案。

## Canonical Specs

- 当前已接受规范的唯一 canonical baseline 是以下 8 个文件：
  - `openspec/specs/identity-access/spec.md`
  - `openspec/specs/agent-model/spec.md`
  - `openspec/specs/business-application/spec.md`
  - `openspec/specs/channel-conversation/spec.md`
  - `openspec/specs/execution-delivery/spec.md`
  - `openspec/specs/builtin-tool-resource/spec.md`
  - `openspec/specs/governed-api-capability/spec.md`
  - `openspec/specs/platform-operations/spec.md`
- 一般规格、设计、实现、评审和诊断任务默认只读取与请求领域相关的 canonical spec，不得递归加载全部规格。
- `openspec/changes/<name>/` 仅在用户明确指定该 active change，或正在执行 propose、apply、sync、archive 工作流时读取；其 delta 必须相对于 canonical baseline 解释。
- `openspec/changes/archive/` 仅在用户明确要求历史、审计或追溯时读取。Archive、proposal、design、tasks、evidence 和迁移快照都是非规范历史证据，不得覆盖 canonical Requirement。
- `openspec list --json` 可用于发现 active change，但不得因此读取无关 change 内容。
- ADR、运行手册和 `docs/reference/chatgpt-context/` 是辅助说明，不是当前规范的替代来源；与 canonical spec 冲突时，应提出明确 change，不得静默选用辅助文档。
- Canonical spec 表达已接受规范，不自动证明运行能力已经实现。需要判断当前实现状态时，仍须核对代码、migration、测试和必要的运行证据，并区分 `Confirmed-current` 与 `Documented-intent`。

## 安全边界

- 不得读取、打印或持久化真实 Secret、Token、密码、模型 Key、Cookie、数据库凭据或原始业务消息。
- 不得把历史 archive 中的凭据示例、现场记录或旧配置复制到当前代码、提示词、日志或规范。
