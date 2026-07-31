# Capability Draft 使用乐观锁并幂等原子发布

Capability Draft 每次保存必须提交 `expected_revision`；Revision 冲突时拒绝覆盖并要求管理员刷新后重新合并。Verify 证据绑定 Draft Revision 和规范化内容 Hash，任何业务 Schema、Handler、Connection 或 Mapping 变化都会使旧验证失效。Publish 必须提交已验证 Revision、内容 Hash 和幂等键；同一幂等键的重复请求返回同一个 Capability Release，不创建重复版本。发布事务原子创建或引用 Capability Revision、创建 Handler Revision、编译 Mapping Plan 并创建 Capability Release，任一步骤失败都整体回滚。
