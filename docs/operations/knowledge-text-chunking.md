# ONES 知识文本清洗与分块

本阶段处理已导入 `knowledge` 的离线缺陷文本，生成可追溯的事实片段和待向量化文本。仍使用现有 PostgreSQL 数据库的 `knowledge` schema，不另建数据库、不覆盖来源版本。

不执行在线采集、图片/附件下载、OCR、模型调用、Qdrant 写入、MCP 发布或授权变更。`storage_only` 和 `offline_unverified` 状态不因分块完成而改变。规则分块通过不等于召回效果验收通过。

## 存储与引用

新增两表，由迁移 `133_expand_knowledge_chunks` 管理：

| 表 | 主要字段与作用 |
| --- | --- |
| `knowledge.document_chunk_set` | `document_id`、`document_revision_id`、`source_content_hash` 绑定来源；`profile_version`、`profile_hash`、`profile_config` 记录规则；`normalized_fields` 保留清洗后的完整字段；`quality`、`chunk_count`、`output_hash` 记录完整结果 |
| `knowledge.document_chunk` | `chunk_set_id`、`ordinal` 定位块；`chunk_kind` 区分问题/方案；`source_field`、`source_start`、`source_end` 定位证据；`evidence_text` 与 `embedding_text` 分开；保存对应长度、摘要和质量标记 |

`source_start`/`source_end` 是 **normalized_fields 对应字段的 Unicode 字符左闭右开区间**。不是源 HTML、文件字节或未经清洗正文的位置。引用链为 `chunk → chunk_set → document_revision`；不能只凭片段 ID 判断当前版本或访问权限。

集合由来源版本和完整配置摘要共同确定，块由集合与顺序确定。同一版本跨知识库可以复用，但当前有效性必须结合当前文档版本、文档 active 状态及 included 收录关系判断；本阶段不提供对外查询入口。

## v1 规则

- 仅支持既有 `ones-offline-text/v1` 的缺陷；知识库必须为 storage_only、有效收录来自同一来源。
- 规范化 CRLF、控制字符和边缘空白行；保留代码缩进、内部空白、错误码、数字，不重复 HTML 解码或做 Unicode 兼容折叠。
- 正文不超过 1,200 字符时整体保留；长文软目标 900、硬上限 1,200，优先段落/步骤/行/句末，重叠最多 120 字符。短围栏代码块保持整体，超长代码/日志按行续块，极长单行允许硬切并标记。
- 正文所有非空白字符必须有证据覆盖，尾部不得截断。每块 evidence_text 必须精确等于对应来源切片。
- `attributes.solution_text` 非空且非明确状态占位时独立生成方案块；与正文完全相同则不重复。保留 absent、status_only、duplicates_body、unsupported_type、included 等处理状态。不推断根因。
- embedding_text 用原有标题、项目及有限产品/模块/环境/版本上下文和证据组成；方案块额外包含短问题片段。上下文最多 550，完整文本最多 1,800 **字符**。这不是 Embedding 模型 token 上限；接模型时必须单独验证。
- 上下文可裁剪并标记 `context_truncated`，证据不可为满足模板预算而截掉；图片/讨论/附件未采集只标记，不生成对应内容。

规则、清洗及模板版本均在 profile 中。规则变化应建立新配置/版本，新建派生集合，不覆盖旧结果或直接修改历史迁移。

## 操作

在仓库根目录使用当前源码构建的 migrator 镜像。迁移只由 one-shot Migrator 执行；分块 CLI 不执行 DDL。

```sh
# 合成示例：不访问数据库、不载入真实配置
docker compose run --rm --no-deps migrator python -m app.cli.prepare_knowledge_chunks --demo

# 默认只读预检；允许 head 132 或当前 head 133
docker compose run --rm --no-deps migrator python -m app.cli.prepare_knowledge_chunks

# 正式迁移（仅在已批准迁移窗口执行）
docker compose run --rm --no-deps migrator python -m app.cli.migrate --build knowledge-chunks-20260916

# 显式写入；要求当前 head
docker compose run --rm --no-deps migrator python -m app.cli.prepare_knowledge_chunks --commit

# 同一命令再次执行即完整性复查及幂等重放
docker compose run --rm --no-deps migrator python -m app.cli.prepare_knowledge_chunks --commit
```

默认知识库 `ones-defects-offline`、期望文档数 5,000，可用 `--knowledge-base-code`、`--expected-count` 显式指定；期望数量范围 1–200,000，实际数量不一致则写入前拒绝，不静默限量。扫描使用主键游标，每页 100 条，每 250 条打印安全进度。

合成示例中的方案 embedding_text 结构为：原有标题、合成问题片段、项目/模块、方案证据。实际运行只输出计数、长度直方图、质量标记及摘要；不得将真实正文、标题、URL、凭据添加到运行日志或验收文档。

## 失败与恢复

来源锁与导入共用。每个文档的集合及全部块在同一事务写入；写入前锁定并复查当前版本、文档及收录状态。一个文档失败不会留下半组结果，之前已提交的完整集合保留。

重新执行时重新计算并验证既有完整结果后复用。若返回 `knowledge_chunk_stored_result_conflict`，表示已有内容与确定性结果不一致，应停止排查，不自动删除或覆盖。`knowledge_chunk_source_changed` 表示输入状态发生变化；稳定来源后重新预检并执行。其他失败只输出固定错误码，不输出异常正文。

迁移前后比较原七表计数和内容摘要；实际提交与重放应具有相同输入/输出摘要。独立 SQL 验收检查类型计数、长度、精确来源切片、唯一性和全量覆盖。聚合质量标记是**块数**，不是去重文档数。

## 部署边界

执行本阶段时原应用栈已停止，仅恢复原 PostgreSQL 数据卷。更新 schema 后须使用包含相同迁移 head 的新后端镜像；只构建镜像不代表服务已部署或 API 已通过验收。不为完成离线分块擅自启动整个应用栈。

后续依次是选定 Embedding 模型及数据出境边界、验证 token 预算、向量化与 Qdrant、召回评测和知识库 MCP/授权。当前结果不能直接视为 Agent 可检索资源。
