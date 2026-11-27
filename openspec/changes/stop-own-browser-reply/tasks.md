# Tasks

## 1. 插件本人取消权限

- [x] 1.1 在浏览器扩展协议 v1 定义本人取消接口与四种回执，核对协议说明、JSON Schema 和 API 返回字段。
- [x] 1.2 校验插件来源、应用授权与任务归属。用 `test_only_the_plugin_message_owner_can_stop_a_reply` 验证普通用户可取消自己的插件任务，其他账号、错误来源、无凭据或应用已停用时请求被拒绝。
- [x] 1.3 用 `test_plugin_cannot_cancel_its_users_own_debug_job` 验证同一普通用户在同一业务应用下使用插件取消自己的调试任务会得到 404，任务状态和取消意图保持原值。

## 2. 执行终态

- [x] 2.1 复用已有取消与审计流程，运行 `test_cancel_requires_manage_and_records_durable_idempotent_intent` 验证管理端权限，核对本人入口写入的操作人。
- [x] 2.2 用 `test_stopping_a_running_plugin_reply_waits_for_the_worker_outcome` 验证运行中的任务先返回 `cancel_requested`，随后快照按 Worker 的实际终态显示取消或失败。运行 `test_runtime_replica_pool.py -k cancel` 验证准入和取消并发。

本地回归使用合成账号和任务。该变更的 delta 已同步到 `execution-delivery` 主规格。
