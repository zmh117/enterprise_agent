# Capability Release 支持软废弃

Capability Release 的不可变配置内容与发布后的运维状态分离。新 Release 初始为 `ACTIVE`；`DEPRECATED` 允许既有 Application Publication 继续执行，但阻止新 Agent 配置、应用绑定或应用升级选择，并可记录废弃原因和 `replacement_release_id`；`DISABLED` 用于紧急阻断，所有新调用失败关闭，并按 ADR-0043 作为第一版受治理 API Capability 的运行时回退手段；`ARCHIVED` 只保留历史记录并从日常选择列表移除，应在没有活动应用继续依赖后使用。软废弃不会按日期自动禁用，也不会自动升级、回退或修改既有应用。任何状态变化都不得修改被冻结的 Capability、Handler、Connection 或 Authentication Profile 内容。
