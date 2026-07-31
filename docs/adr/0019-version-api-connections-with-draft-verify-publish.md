# API Connection 使用 Draft、Verify、Publish 生命周期

API Connection 采用 `DRAFT → VERIFIED → PUBLISHED`。固定 Origin 和 Authentication Profile 必须由当前授权管理员使用自己的外部身份完成受控验证；首个 ONES Connection 尚无可绑定发布版本时，按 ADR-0029 使用不持久化密码或 Token 的启动验证。Published Connection Revision 不可修改或普通删除。修改 Origin 或认证规则必须创建新版本，依赖的 Capability 和 Application 显式重新验证发布；不兼容认证版本之间不得复用旧用户 Token。
