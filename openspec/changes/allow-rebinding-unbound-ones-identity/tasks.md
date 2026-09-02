## 1. 数据库契约

- [x] 1.1 新增顺序 migration，在 SQLite 无损重建身份表并在 PostgreSQL 移除旧全局唯一约束
- [x] 1.2 创建 provider-aware 部分唯一索引，保持 ONES 当前身份唯一性、钉钉全状态唯一性及既有索引和外键
- [x] 1.3 扩展 schema migration 回归，验证历史数据保留、SQLite 外键完整性和新唯一约束行为

## 2. ONES 绑定实现

- [x] 2.1 调整身份仓储，使 ONES 绑定只把 `enabled`、`disabled` 视为当前冲突并忽略 `unbound` 历史
- [x] 2.2 将并发插入的当前身份唯一冲突映射为安全稳定的 `identity_conflict`，并保持事务回滚

## 3. 生命周期回归

- [x] 3.1 增加 A 解绑后 B 重新验证绑定成功的 API/服务测试，并验证 A 的身份、Credential 与审计历史不被改写
- [x] 3.2 增加 disabled 不释放、B 绑定后 A 不能反向绑定以及并发唯一仲裁测试
- [x] 3.3 运行钉钉身份聚焦回归，确认已解绑钉钉身份仍只能由原人员恢复

## 4. 验证

- [x] 4.1 运行身份、migration 聚焦测试和相关静态检查
- [x] 4.2 运行严格 OpenSpec 校验、Compose 配置校验和 `git diff --check`
