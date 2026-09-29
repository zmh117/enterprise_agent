# ONES 受管全量采集（候选阶段）

此入口把三类 ONES 工作项（缺陷、工单、Story 及其子任务）写入 `knowledge` 的候选修订。它**不**请求评论、附件内容或图片，不下载文件，不修改当前知识库收录、Qdrant 索引、资源发布或角色授权。首次运行从 `first_date` 按北京时间创建日逐日完整枚举；首次成功激活后的每小时运行只复核当天及此前 6 个自然日创建的根工作项，并重新读取这些 Story 的子任务。此策略不是“按更新时间增量”：更早创建的根项即使后来更新，也不会被本轮刷新。

## 启用前提

- 仅在能访问真实 ONES 的目标环境运行；本机合成 Provider 测试不是正式 ONES 验收。
- PostgreSQL 必须处于当前 schema head。配置只保存来源范围与 `secret://platform/<code>` 凭据引用；不在 JSON、环境变量或日志里填写 Token。
- 凭据中心该引用解密后的内容是受管采集身份的 JSON 对象，仅有 `token` 与 `user_id` 两项。采集身份与 Knowledge MCP 的当前用户只读身份分离，采集权限不传递给检索用户。
- 执行 `once` 的容器必须像 ONES MCP 一样挂载平台的只读 Master Key，并设置 `APP_CONFIG_MASTER_KEY_FILE` 指向容器内文件；CLI 会从该文件加载 Key，再解析凭据引用。文件缺失或格式、权限不合规时提前返回 `knowledge_collection_master_key_unavailable`，不会连接数据库或尝试 ONES；不得改用明文环境变量。
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

`configure` 新建或修改后始终停用；修订号需按 `status` 的结果进行 CAS。`once` 仅在显式启用后运行，失败可用相同活动 run 重放未完成日期，逐条候选按内容哈希幂等。`status` 只输出安全计数、日期进度和固定错误码；`cancel --run-id <id> --commit` 可取消无人持有来源锁的未完成 run。

停用会在下一次批次/日期检查时使正在采集的 run 取消；已发出的单个请求最多等待既定 30 秒。详情请求最多 16 路并发；仅对限流和暂时不可用做有界重试，身份/范围/内容冲突不重试。每个创建日先完成全部类型、所有页与 Story 子任务核对，才把下一日期与累计数量同事务写入检查点。重启后跳过已完成日期；未完成日期重新枚举，已提交候选按 UUID 幂等复用。完成整轮前不清洗、索引或发布部分结果。

## 失败及边界

重复页、游标无进展、计数漂移、空页、详情 ID/类型/项目冲突、单日单类型达到 1000 项、总量超过 200000、首次全量来源为空、扫描范围内已有根项不可见，均使本轮保持未完成；绝不因缺席推断删除。后续 7 天窗口允许没有新项。更早创建的根项及其子树被明确排除在小时刷新范围外；若业务要求补录这些更新，需另行设计回补流程。401、403、404、限流、Provider 不可用与响应过大分别记录固定错误码，不回显原始响应。

本入口结束于 `STAGED` 候选；完整清洗分块、Embedding、Qdrant 完整性校验和受管切版使用[同步入口](knowledge-ones-hourly-sync.md)的 `once`。未完成这些阶段前，不能把候选计数当作当前可检索内容。每小时 worker 另需显式启用，真实 ONES 的过滤、排序、项目范围及版本戳合同仍需在目标环境单次运行验收后才可授权调度。
