## Why

工具资源表单切换数据范围的 Environment 或 Base 时会无条件添加空 `workshop_code`，而 Loki 数据范围契约不接受该字段，导致新建和编辑 Draft 保存失败。需要修正前端提交契约，而非放宽 Loki 的范围限制。

## What Changes

- Loki 范围编辑不再生成无意义的 Workshop 字段。
- 新建和编辑使用同一个请求清理逻辑，仅移除 Loki 范围中的空 Workshop 占位字段；非空非法字段仍须被拒绝，不能静默放宽目标范围。
- 保留数据库、Redis 的 Workshop 与前缀字段，以及现有资源身份和发布规则。
- 补充两类提交路径、范围切换及后端严格校验的回归。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`：明确统一 Draft 表单在 Loki 场景下不得提交空 Workshop 占位字段，并保证其他资源的车间范围不受影响；不扩大现有 Loki 范围能力。

## Impact

影响前端工具资源表单、资源请求序列化及相关测试。无需数据库迁移、不改后端允许字段、不新增依赖、不修改或发布用户已有资源。
