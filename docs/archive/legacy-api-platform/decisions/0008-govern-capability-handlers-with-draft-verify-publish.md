# Capability Handler 使用 Draft、Verify、Publish 生命周期

Capability Handler 采用 `DRAFT → VERIFIED → PUBLISHED`。Draft 保存和发布按 ADR-0046 使用乐观锁、内容 Hash、幂等键和原子事务；任何 Draft 变更都会使旧验证结果失效，只有最新 Draft 通过静态校验和受控真实调用后才能发布。Published Revision 不可修改或普通删除，只能 Disable 或 Archive。第一版不设置双人审批，拥有 Handler 发布权限的管理员可以完成验证与发布，所有动作均记录审计。
