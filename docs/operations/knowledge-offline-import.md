# ONES 缺陷离线文本入库

## 范围与存储位置

使用平台现有 PostgreSQL 数据库中的 `knowledge` schema。迁移为
`131_expand_knowledge_text_storage.sql`，必须由平台 one-shot Migrator 执行。
导入 CLI 不会自动建表，也不会修改 `public` 中的业务记录、资源发布或角色授权。

本阶段只处理用户指定的缺陷导出：正文、字段、版本、知识库收录和关联引用。
不会调用真实 ONES、下载图片或附件、运行 OCR、调用 Embedding、写 Qdrant，
也不会新增 MCP 工具或 Web 页面。`storage_only` 知识库不是可供 Agent 使用的已发布资源。

| 表 | 职责与关键字段 |
| --- | --- |
| `knowledge.source` | 来源命名空间：`code`、`source_system`、`origin_state`、`identity_metadata` |
| `knowledge.document` | 工作项稳定身份：`source_id`、`source_object_type`、`external_id`、`external_number`、`document_kind`、`current_revision_id`、`lifecycle_state` |
| `knowledge.document_revision` | 每次采集到的新版本：`title`、`body_text`、项目/状态 ID 与名称、源时间、`source_snapshot`、`attributes`、`completeness`、`normalizer_version`、`content_hash` |
| `knowledge.knowledge_base` | 逻辑知识库；与来源分开；本阶段状态为 `storage_only` |
| `knowledge.knowledge_base_document` | 多对多收录；同一工作项进入多个知识库不复制正文 |
| `knowledge.import_run` | 文件校验摘要、预检契约、处理进度、结果计数、安全错误码和恢复检查点 |
| `knowledge.document_relation` | 绑定证据版本的原始关联观察；保存两端来源/对象类型/外部 ID、原始类型及方向、可空目标内部 ID |

所有内部 ID 使用文本形式的 UUID；ONES 外部 ID 按不透明文本处理，不转换为数据库 UUID。
`document_kind` 预留 `defect`、`ticket`、`requirement`、`article`；当前 CLI 固定导入 `defect`，
不是通用工单/需求导入器。之后接入其他类型时复用稳定工作项身份、版本与关联表，扩展对应采集契约。

## 本机已完成入库

2026-09-14，本机 `enterprise_agent` 数据库已迁移至 131 并完成正式导入：
5,000 个缺陷、5,000 个内容版本、5,000 条知识库收录，2,407 条关联观察。
其中 52 条目标已解析，2,355 条仅保留外部引用。相同输入重放不增加记录，API 正常就绪。
详细统计和部署证据见 `openspec/changes/import-ones-knowledge-text-foundation/evidence.md`。

## 当前离线来源

输入没有经过确认的 ONES 实例/团队身份，不能绑定到任意已有 Connector。
默认登记为 `ones-offline-export`，状态 `offline_unverified`；逻辑知识库为
`ones-defects-offline`。此来源只能代表这批离线数据及确认属于同一来源的后续导出。
**不要将其他团队/实例的数据混用此 code。** 实时同步前必须先确认实例和团队、完成身份映射，
不能仅凭项目名称或内容相似度合并来源。

## 输入、字段与内容边界

- 默认读取 `缺陷完整_5000.jsonl` 与 `缺陷list_5000.jsonl`，不重复读取 sample 文件。
- 全批预检要求数量正确、UUID 唯一且两份 ID 集合一致；标题、编号、创建时间必须匹配。
- 完整导出的 `project_uuid`、`status_uuid`、`sprint_uuid` 是展示值，不当作真正 ID；
  真 ID 来自 list 对应对象，展示名称分开保存。
- 本导出契约将 `create_time`、`createTime`、`server_update_stamp` 解释为 epoch 微秒；
  校验时间范围，并保留原始更新戳。其他 API/导出须独立验证单位，不复用猜测。
- `body_text` 优先保存清洗后的纯文本描述；空描述才回退到富文本提取结果。
  解决方案、原因、环境、模块、版本、严重程度等进入 `attributes`，未知自定义字段保留在
  `attributes.unmapped_fields`。这些字段不是已经生成的 `embedding_text`。
- `source_snapshot` 是经过清洗的来源证据，**不是逐字原始归档**：移除 URL、内嵌数据、
  常见凭据字段及疑似凭据片段；原始本地文件不修改。清洗为保守规则，可能误删含敏感词的行，
  不能视为未来对外发送数据前的完整安全审查。
- 图片只保留出现顺序、可用附件 ID、原富文本定位和 `not_collected` 状态；不保存可访问地址或 Base64。
  定位指向清洗前富文本提取文本，不是 `body_text` 的可直接切片偏移。
- `discussion_count`、`attachment_count` 仅是数量；没有讨论正文和附件正文，完整性明确标记为未采集。

## 关联与幂等性

`links` 保存的是“从当前工作项看到的关联观察”，不是已经解释的业务边。
`link_in_desc` / `link_out_desc` 和来源关联类型 ID 原样存储，`mapping_state=unmapped`。
不把所有关系统一叫作“关联”，不猜测“缺陷属于需求”等语义，不跨观察去重相反方向。

`related_tasks` 不等于完整工单，只保留外部 ID 和原始可读标记。
目标尚未入库时 `to_document_id` 为空；后续同来源工作项入库会补齐。原始可读标记不是系统授权。
没有把本次未观察到的关联判为已删除；历史观察绑定历史版本，未来当前态查询须按当前证据版本筛选。

同来源、同对象类型、同外部 ID 只创建一个 `document`。同一批文件再次提交返回 `replayed=true`，
不增加版本、收录或关联。同一内容从其他批次进入不创建版本；新时间戳内容创建新版本；旧版本不覆盖新版本；
同一时间戳但内容不同报冲突。每条文档、版本、关联和批次进度在同一事务提交。
中断后使用相同文件和配置重试，从上次已提交位置恢复；同来源并发导入由 PostgreSQL advisory lock 拒绝。
已删除/不可用文档不会被新的导入自动恢复，已移除收录也不会被悄悄恢复。

## 操作步骤

1. 确认目标数据库、现有迁移 head 和目录来源；不要输出连接串、环境秘密或业务正文。
2. 运行预检（不加载数据库配置、不写入数据库）：

   ```sh
   PYTHONPATH=backend .venv/bin/python -m app.cli.import_ones_knowledge \
     --input-dir '/Users/mhz/Develop/enterprise_agent/知识库/数据/5000条完整数据'
   ```

3. 安排平台部署窗口。平台对迁移 head 严格校验：旧版容器不识别 131，
   **不能只迁移数据库就继续将旧版 readiness 视为正常**。
   先准备包含本次代码和迁移的相关服务镜像，确认可以短暂停服，再按现有发布流程执行。
   one-shot 仅调用迁移入口，不要顺便执行无关 bootstrap、授权或 Agent 发布：

   ```sh
   docker compose run --rm --no-deps migrator python -m app.cli.migrate
   ```

4. 更新受迁移 head 约束的运行服务，确认数据库、服务健康检查及 `/api/ready` 正常。
   使用已配置的容器环境认证，输入目录只读挂载；不要把业务导出 COPY 到镜像中：

   ```sh
   docker compose run --rm --no-deps \
     -v '/Users/mhz/Develop/enterprise_agent/知识库/数据/5000条完整数据:/knowledge-input:ro' \
     migrator python -m app.cli.import_ones_knowledge \
     --input-dir /knowledge-input --commit
   ```

5. 核对 `import_completed` 的计数和 `verification`，再执行相同命令验证重放不增加记录。
   CLI 每 250 条只输出累计进度，错误只输出安全错误码和可用行号。
   不查询/打印 `title`、`body_text`、快照或人员/项目实际名称作为验收输出。

第一次导入本批文件的预期：5,000 个缺陷、5,000 个版本、5,000 条收录，25 个项目，
2,407 条关联观察，其中 52 条可解析到本批文档、2,355 条只保留外部引用；
7,798 个图片引用但没有图片文件。关联未解析不是导入失败。

## 失败处理与后续工作

输入错误在任何写入前拒绝；中途失败保留已提交行，修复环境后使用原文件重试。
不要通过删批次、改 hash、改历史版本或回退 migration ledger 来“修复”导入。
暂不提供破坏性回滚命令；需要撤销时先确认批次、共享收录与后续版本依赖，再设计受控操作。

本批可重复执行不意味着实现了定时增量采集。后续仍需独立设计/验收：来源身份确认、
工单/需求采集、删除/权限撤销传播、知识库角色授权与发布、分块与 Embedding 版本、Qdrant 索引及召回。
恢复 PostgreSQL 时应包含整个 `knowledge` schema 及相关迁移账本，不能只备份正文表。

## 测试

合成测试不含真实缺陷内容：

```sh
.venv/bin/pytest -q backend/tests/test_knowledge_import.py \
  backend/tests/test_schema_migration_runtime.py \
  backend/tests/test_schema_fact_source_manifest.py
```

设置 `KNOWLEDGE_TEST_POSTGRES_DSN` 后额外执行真实 PostgreSQL 测试；必须指向隔离测试数据库，
测试会运行平台 Migrator 并插入合成数据，不应指向实际运行库。未设置时该项显式跳过。
