# ONES 受管全量采集（候选阶段）

此入口把三类 ONES 工作项（缺陷、工单、Story 及其子任务）写入 `knowledge` 的候选修订。它**不**请求评论、附件内容或图片，不下载文件，不修改当前知识库收录、Qdrant 索引、资源发布或角色授权。每次运行均按固定 Team、项目和类型完整枚举，并重新读取每个 UUID 的 `/info`；不使用导出脚本的 `done` 跳过规则，也不声称 ONES 支持已验证的“按更新时间增量过滤”。

## 启用前提

- 仅在能访问真实 ONES 的目标环境运行；本机合成 Provider 测试不是正式 ONES 验收。
- PostgreSQL 必须处于当前 schema head。配置只保存来源范围与 `secret://platform/<code>` 凭据引用；不在 JSON、环境变量或日志里填写 Token。
- 凭据中心该引用解密后的内容是受管采集身份的 JSON 对象，仅有 `token` 与 `user_id` 两项。采集身份与 Knowledge MCP 的当前用户只读身份分离，采集权限不传递给检索用户。
- 来源主机必须属于 `ONES_MCP_PROVIDER_ALLOWED_HOSTS`。HTTPS 始终可用；HTTP（包括生产环境）须显式设置 `ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL=true`，并把目标主机加入允许列表。HTTP 会明文传输采集 Token 与业务数据，只能在可信网络边界内使用。单次 HTTP 请求最长 30 秒、响应最多 1 MiB，禁用代理与重定向。
- 本仓库的 [`ones-collector.example.json`](../../knowledge/ones-collector.example.json) 已填入本次指定的 ONES 地址、Team、37 个项目与类型 UUID；目标环境仍需提供对应允许列表和凭据中心引用。`resource_ids` 留空，不会自动首次发布知识资源或授予角色权限。
- 配置中的 `first_date` 必须覆盖全部需要收录工作项的创建日期；项目和类型 UUID 必须完整。Story 子任务通过 Story 详情列出的 UUID 单独取 `/info`，不是从父类型的列表推断。

## 明确操作

先复制并填写 [`knowledge/ones-collector.example.json`](../../knowledge/ones-collector.example.json) 中的非敏感来源范围。以下命令在后端运行环境执行，`<code>` 和文件路径由操作者明确填写；不要把凭据正文作为 CLI 参数传入。

```bash
python -m app.cli.collect_ones_knowledge --mode configure --binding-code <binding-code> --source-code <source-code> --configuration-file <collector.json> --expected-revision 0 --commit
python -m app.cli.collect_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.collect_ones_knowledge --mode enable --binding-code <binding-code> --expected-revision 1 --commit
python -m app.cli.collect_ones_knowledge --mode once --binding-code <binding-code> --commit
python -m app.cli.collect_ones_knowledge --mode disable --binding-code <binding-code> --expected-revision 1 --commit
```

`configure` 新建或修改后始终停用；修订号需按 `status` 的结果进行 CAS。`once` 仅在显式启用后运行，失败可用相同活动 run 重放已提交页，逐条候选按内容哈希幂等。`status` 只输出安全计数和固定错误码；`cancel --run-id <id> --commit` 可取消无人持有来源锁的未完成 run。

停用会在下一次受限请求前使正在采集的 run 取消；已发出的单个请求最多等待既定 30 秒。重启后若有相同绑定的活动候选，`once` 从来源重新完整枚举，已提交的页逐条幂等跳过；持久检查点保留最后页/分片，但首版**不**从游标直接跳过前面的来源请求。重放仍核对所有已有 UUID，避免遗漏更新。

## 失败及边界

重复页、游标无进展、计数漂移、空页、详情 ID/类型/项目冲突、单日窗口达到 1000 项、总量超过 200000、全部来源为空或已有项在固定范围内不可见，均使本轮保持未完成；绝不因缺席推断删除。401、403、404、限流、Provider 不可用与响应过大分别记录固定错误码，不回显原始响应。

本入口结束于 `STAGED` 候选；完整清洗分块、Embedding、Qdrant 完整性校验和受管切版使用[同步入口](knowledge-ones-hourly-sync.md)的 `once`。未完成这些阶段前，不能把候选计数当作当前可检索内容。每小时 worker 另需显式启用，真实 ONES 的过滤、排序、项目范围及版本戳合同仍需在目标环境单次运行验收后才可授权调度。
