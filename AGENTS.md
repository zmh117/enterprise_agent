# Enterprise Agent 协作约束

## 工作方式

- 需求不清时，不准直接执行；必须先向用户确认规格。
- 不要默认最小改动，默认选择稳健方案。
- 禁止过度设计，不引入没有当前需求或调用者的扩展层。

## Canonical Specs

- 当前已接受规范的唯一 canonical baseline 是以下 10 个文件：
  - `openspec/specs/identity-access/spec.md`
  - `openspec/specs/agent-model/spec.md`
  - `openspec/specs/business-application/spec.md`
  - `openspec/specs/channel-conversation/spec.md`
  - `openspec/specs/document-file-processing/spec.md`
  - `openspec/specs/execution-delivery/spec.md`
  - `openspec/specs/builtin-tool-resource/spec.md`
  - `openspec/specs/governed-api-capability/spec.md`
  - `openspec/specs/platform-operations/spec.md`
  - `openspec/specs/task-file-workspace/spec.md`
- 领域导航见 `openspec/specs/README.md`；它只负责定位，不是第 11 份主规格。
- 一般规格、设计、实现、评审和诊断任务先按领域定位，默认只读取与请求领域相关的 canonical spec，不得递归加载全部规格。涉及代码事实时继续核对相关源码、迁移与测试，不从旧文档推断已实现能力。
- `openspec/changes/<name>/` 仅在用户明确指定该 active change，或正在执行 propose、apply、sync、archive 工作流时读取；其 delta 必须相对于 canonical baseline 解释。
- 历史 `openspec/changes/archive/` 已删除，追溯使用 Git 历史。今后 archive 工作流产生的目录仅在用户明确要求历史、审计或追溯时读取。Archive、proposal、design、tasks 和 evidence 都是非规范历史证据，不得覆盖 canonical Requirement。
- `openspec list --json` 可用于发现 active change，但不得因此读取无关 change 内容。
- `docs/` 下的架构概览、运行手册、ADR 以及各级 README 是辅助说明，不是当前规范的替代来源；与 canonical spec 冲突时，应提出明确 change，不得静默选用辅助文档。
- Canonical spec 表达已接受规范，不自动证明运行能力已经实现。需要判断当前实现状态时，仍须核对代码、migration、测试和必要的运行证据，并区分 `Confirmed-current` 与 `Documented-intent`。
- 真实环境验收欠账集中记录在 `docs/acceptance-backlog.md`。关闭或归档 change 不代表未勾选任务已完成；取得真实证据前不得补勾或移出欠账。
- 同步或归档 delta 时，先按领域导航映射到上述 10 个领域并核对代码；不得按旧目录名重新创建零散主规格。未能确认的旧提案不自动成为当前能力。

## 安全边界

- 不得读取、打印或持久化真实 Secret、Token、密码、模型 Key、Cookie、数据库凭据或原始业务消息。
- 不得把 Git 历史或归档中的凭据示例、现场记录或旧配置复制到当前代码、提示词、日志或规范。

- Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.
  避免不必要的次要标签和描述。让布局自己说话。
