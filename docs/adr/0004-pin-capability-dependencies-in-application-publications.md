# 应用发布冻结 Capability 的精确执行依赖

业务应用发布时冻结 Agent Publication、Application Capability Allowlist，以及其中 API Capability、Capability Handler 和 API Connection 的精确发布版本。后续 Agent、Handler 或 Connection 新版本不会自动改变既有应用；升级必须重新校验、发布并激活。Capability Release 被软废弃时，既有应用继续执行但不能再供新绑定或升级选择；被冻结的 Release 或依赖被禁用后，新调用失败关闭。不因废弃或禁用自动升级、回退或切换到其他版本，以避免未经审核的线上行为漂移。
