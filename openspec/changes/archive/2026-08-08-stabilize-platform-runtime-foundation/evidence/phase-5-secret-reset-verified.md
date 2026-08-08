# Phase 5 旧平台凭据清理执行与验证

记录时间：2026-07-29T17:56:01+08:00  
结果：APPLIED / VERIFIED

## 1. 已确认操作

```text
operation_id: platform_secret_reset_0e086a4a-eebe-4069-8c55-55ba8fec85e1
inventory_digest: ae6699fab921d0b671896f5b97c25671ac9ab6d633c157a71cb179abeb9a46d6
backup_reference: file:///Users/mhz/Backups/enterprise_agent/secret-reset-20260729-172433
```

执行前重新校验了备份中 8 个载荷的 SHA-256、PREPARED manifest、
PostgreSQL dump 可读性、数据库库存和 RabbitMQ 排空状态。

维护冻结时：

- 19 个 Agent Job 全部为 `SUCCEEDED`；
- Job/Delivery/Channel Outbox 没有 pending、running、retry 或 dead 记录；
- 所有 RabbitMQ queue 的 messages ready、unacked、consumers 均为 0；
- 平台 PostgreSQL 没有其他业务连接。

## 2. 回滚演练与正式事务

正式 apply 前使用同一 SQL 完整执行一次事务并以 `ROLLBACK` 结束。演练验证：

- PREPARED audit、operation ID 和 digest 精确匹配；
- 目标数量保持 3 个 Secret、14 个密文版本、1 个 runtime value、
  4 个 model connection revision；
- 其他 Connector、Secret reference、Resource 与 Webhook 依赖数均为 0；
- 用户、外部身份、RBAC 和 DingTalk Connector 的安全 digest 与准备基线一致；
- 删除顺序、外键约束、模型 identity 重置和事务内 verify 全部通过。

修正演练中发现的 JSON 数组 SQL 别名冲突后，第二次演练完整通过；第一次失败事务
已由 PostgreSQL 自动回滚，数据库仍保持准备清单状态。

正式事务随后对相同 SQL 执行 `COMMIT`，结果：

| 对象 | 删除数量 | 剩余数量 |
|---|---:|---:|
| `platform_secret` | 3 | 0 |
| `platform_secret_version` | 14 | 0 |
| Anthropic runtime config value | 1 | 0 |
| `model_connection_revision` | 4 | 0 |

`default-deepseek-anthropic` identity 保留，状态为：

```text
current_revision_id: null
status: rotation_required
revision: 0
```

数据库已保存不含凭据材料的 `platform_secret_reset_applied` 审计。

## 3. 服务恢复验证

恢复 API、Internal API Platform、DingTalk Runtime、Admin Web 及所有核心
Worker 后：

- API `/api/ready`：`status=ready`、schema head `024`；
- API runtime config：`source=database`、`degraded=false`、`errors=[]`；
- Internal API `/ready`：`status=ready`、resource count `0`、
  `degraded=false`；
- 固定 Master Key 文件：容器内 mode `0400`、size `61`、
  Key ID `3c49324f76f17310`；
- 启动日志没有 `平台凭据解密失败`、decrypt exception、Traceback 或
  ERROR/CRITICAL；
- 当前 RabbitMQ queue 全部为空，核心消费者已恢复；
- 3 个 DingTalk Connector 保留且配置 revision 未变化。

数据库保存了 `platform_secret_reset_verified` 审计，记录上述安全计数与
readiness，不包含明文、密文、nonce 或 Master Key。

## 4. 保留对象

事务内 digest 与恢复后数量共同证明以下对象未被本操作删除：

- `app_user`：7；
- `user_external_identity`：7；
- `rbac_role`：3；
- `rbac_user_role`：7；
- DingTalk Connector：3；
- 固定 Master Key、业务应用、Job、Outbox、Delivery、审计及资源 reset 历史。

旧授权 cleanup 与旧 RabbitMQ queue cleanup 仍维持 PREPARED、未执行。

## 5. 未包含的环境凭据

本次已确认 operation 只删除 PostgreSQL 中受旧 Master Key 影响的 Secret、
runtime value 和 model connection revision。恢复后只检查配置状态，不读取或
输出值，发现仓库 `.env` 中以下部署变量仍为非空：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`

它们不经过平台 Secret 加密，因而不受本次 Master Key mismatch 影响，也不属于
已确认 inventory digest。部分 legacy Agent 路径仍可能使用这些部署变量。

若目标是完全从空模型凭据开始，应另行明确确认清空这两个 `.env` 值；清空后需要
重启 API/Worker，再从“模型连接/凭据中心”重新录入并发布新凭据。

## 6. Post-reset Agent 配置恢复回归

清理模型连接版本后，Agent 当前发布快照仍按不可变历史保留其
`model_connection.revision_id`。该引用位于 JSON 文本中，不受数据库外键约束；
原列表实现直接解引用并让 `NotFound` 传播为 HTTP 500，导致 Agent 配置页无法展示。

2026-07-29 完成以下回归修复：

- Agent 列表对确实已删除的模型连接版本降级为
  `model_connection_status=missing_revision`，不吞掉其他完整性异常；
- 管理前端显示“引用版本已删除，请重新配置”；
- 当模型连接 identity 存在但 revision 为 0、current revision 为空时，模型连接页
  仍提供空白 canonical 配置表单；
- 恢复顺序明确为：保存新连接配置、配置 API Key、测试已保存版本、保存并重新发布
  Agent；历史 Agent publication 不被静默改写。

验证结果：

- 后端相关测试：27 passed；
- Agent Profile 前端交互测试：3 passed；
- TypeScript typecheck 与 ESLint：通过；
- Compose 中 `/api/admin/agents` 与 Agent 详情接口返回 200；
- 真实管理页面可见失效引用状态、空白连接配置表单和“保存为新连接版本”，浏览器
  控制台无 error/warn；
- 验证过程未创建新模型 revision、Secret 或 API Key。
