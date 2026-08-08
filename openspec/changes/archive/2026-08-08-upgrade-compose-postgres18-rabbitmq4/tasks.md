## 1. Compose 基础设施升级

- [x] 1.1 将 PostgreSQL 默认镜像改为可通过 `POSTGRES_IMAGE` 覆盖的 `postgres:18`，保持服务名、端口、健康检查和连接契约不变
- [x] 1.2 将 RabbitMQ 默认镜像改为可通过 `RABBITMQ_IMAGE` 覆盖的 `rabbitmq:4-management`，保持 AMQP、Management 端口和应用连接契约不变
- [x] 1.3 为 PostgreSQL 18 与 RabbitMQ 4 增加版本隔离的显式命名卷，并将 PostgreSQL 18 卷挂载到 `/var/lib/postgresql`
- [x] 1.4 更新 `.env.example` 或相关配置说明，记录镜像覆盖变量及生产锁定补丁版本/digest 的方式

## 2. 安全升级工具

- [x] 2.1 实现非破坏性 preflight，报告实际镜像版本/digest、PostgreSQL 连通性、备份目录和 RabbitMQ 三类 Agent 队列的 ready/unacked 状态
- [x] 2.2 实现 PostgreSQL 16 逻辑备份流程，生成不进入 Git 的备份文件与迁移前关键表记录数、配置 revision 校验信息
- [x] 2.3 实现 PostgreSQL 18 新卷初始化、逻辑恢复及 migration/seed 幂等执行流程，恢复失败时非零退出且不删除旧数据
- [x] 2.4 实现迁移后核验，比较关键表记录数、配置 revision，并验证数据库主版本与持久化目录
- [x] 2.5 实现 RabbitMQ 切换保护：任一受管队列存在 ready/unacked 消息时中止，不自动清空队列或删除旧卷

## 3. RabbitMQ 4 任务链路兼容性

- [x] 3.1 验证现有 publisher/consumer 能在 RabbitMQ 4 上幂等声明正常、重试和 dead-letter 拓扑
- [x] 3.2 增加 RabbitMQ 4 成功发布、消费与 ack 的集成测试或 Compose smoke 检查
- [x] 3.3 增加 RabbitMQ 4 可重试失败和不可重试/dead-letter 路径的集成测试或 Compose smoke 检查

## 4. 文档与回滚

- [x] 4.1 编写中文升级文档，分别覆盖全新环境启动和已有 Compose 环境从 PostgreSQL 16/RabbitMQ 3 升级
- [x] 4.2 在文档中明确 PostgreSQL 18 挂载点变化、逻辑迁移步骤、RabbitMQ 排空要求、验收门槛和故障排查
- [x] 4.3 编写不删除旧卷与备份的回滚流程，并将不可逆清理作为验收后的独立人工步骤

## 5. 端到端验证

- [x] 5.1 运行 `docker compose config`，确认镜像默认值、命名卷、依赖和健康检查配置有效
- [x] 5.2 在空卷环境启动 Compose，验证 PostgreSQL 18、RabbitMQ 4 Management、api-server 和 agent-worker 均健康
- [x] 5.3 使用测试数据执行一次 PostgreSQL 16 到 18 的备份恢复演练，并核对关键数据和运行时配置完整性
- [x] 5.4 通过调试 API 提交 Agent Job，验证 job 从 `PENDING` 到 `SUCCEEDED` 且最终报告可查询
- [x] 5.5 执行 retry/dead-letter smoke，并记录 RabbitMQ 4 队列、job 状态和审计数据的一致性
- [x] 5.6 运行相关 Python 测试和 OpenSpec strict validation，记录未执行或依赖外部环境的验证项
