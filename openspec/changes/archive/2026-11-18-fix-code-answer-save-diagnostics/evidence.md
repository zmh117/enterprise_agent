# 验证记录

## 直接原因

- 原任务 job_547a2f6513f0442d8bb9f582ee374584 有 9 条有效 Read 证据，保存未形成 MCP 审计。身份审计确认知识 Principal 于 2026-11-12 10:49:24 +08:00 到期，10:49:35 校验返回 principal_token_expired。SDK 时间线曾折叠为通用工具失败。
- 新模型复测 job_822eeb5aabdd4739b16e44e78f2e9c23 再现另一个阻断：分析期限继承已完成搜索的 360 秒请求截止，提前于原任务结束，授权客户端折叠为 CODE_SOURCE_GRANT_DENIED。没有绕过保存校验或直接补写历史答案。
- 目标 index 584c17ab-a466-59c8-bfdc-e876dfc60c88 配置就绪、增量索引启用，原本无索引任务；并非 Embedding 排队失败。

## 本地检查

- 342 项相关后端回归通过（源码准入、证据、保存、索引、Principal、MCP、Runtime 与事件审计）。
- 最后调整保活使用工具目录已有权限后，52 项凭证/诊断回归通过。12 项 Runtime Compose/打包合同测试通过。
- 修改的 9 个 Python 生产模块 mypy 通过；全仓 ruff lint 通过；修改文件 format、git diff --check、Markdown 链接检查通过。
- 本 change、builtin-tool-resource 和 execution-delivery 规范校验通过。
- 全仓基线仍有独立问题：mypy 在未修改的 code_search_options.py、code_checkout_reader.py、code_source_mount.py 共 3 项；未修改 test_webhook_optional_authentication.py 格式检查失败；task-file-workspace 的既有 2 条 Requirement 位于 Requirements 段外。未将这些检查报告为全仓通过。

## 部署与真实验证

已同步构建并更新 API、两个 Agent Worker、Job/Channel/Webhook/Delivery Dispatcher、tool/ones/dingtalk/file/knowledge MCP、knowledge-sync 和两个 Python Runtime。构建阶段发现 Runtime 精简镜像需显式携带 code_operation_errors.py，已补齐并通过镜像导入自检。两个 Runtime 均健康，Prompt v20，保活周期 30 秒。

仅更新 assist03：Agent 59 → 60，应用 76 → 77，保持 79 个已选工具及原授权、执行/会话策略、触发与投递配置。知识资源及分块/Embedding profile 未重建。knowledge-ops-controller 更新前后均 unhealthy，属于独立运维状态问题，本次不声称全套服务健康。

- 首轮部署后模型任务 job_a47ddee776254bb0af43fd37ec23b451 在检索前置失败，未取得源码与索引，保留 unverified 事实；未把 Job SUCCEEDED 当作业务成功。
- 复测 job_14371d62be154424915f1b4ebda2519a：2026-11-12 16:15:10 至 16:20:05 +08:00，正式源码分析完成，10 条 file_read 全部 validated，保存工具成功。分析截止与 invocation 一致，均为 16:45:11，不再采用单搜索请求截止。
- 16:19:25 知识 Principal 在原票据到期前成功续期，原期限不变；随后保存完成。
- 目标知识库 new、环境 sanjiu、SVN r2：问答 support_status=supported、answer_origin=code_analysis，引用 1 条正式答案，revision_id=5aa0ccdb-8565-5c5f-9b4f-e1eff8755c3f。
- 索引任务 succeeded/done，expected_chunks=completed_chunks=1；实际 Qdrant count=1，集合 code_answers_584c17aba46659c8bfdce876dfc60c88。没有直接 SQL 插入答案或直接写向量。
- 初次缓存复测 job_f5f575eace534b8595176f11c3991e51 同样在工具入口失败，无源码与保存，未改变已成功的索引。未留存原始参数/错误正文，无法追认其具体原因；不将它归因于凭证过期或断言已解释所有偶发失败。
- 补齐 CLI 在进入 MCP 前的参数拒绝诊断：按已声明 schema 保留无值提示，SDK 调用索引不保留知识请求正文；失败提示直接安全投影，避免再被通用 bounded_payload 包装丢失。补充回归共 181 项通过，并更新两个 Runtime。
- 原问题再次复测 job_965af917e5e64f11b8940b99e699278f：16:26:04 至 16:26:54 +08:00，knowledge_list_bases、knowledge_search、knowledge_get_code_answer 全部成功；问答 supported/cache，引用 1 条正式答案，没有新源码分析、没有重复保存或索引。
- 最终实际 Qdrant count 仍为 1。两个 Runtime、API、knowledge-mcp、knowledge-sync 健康。
