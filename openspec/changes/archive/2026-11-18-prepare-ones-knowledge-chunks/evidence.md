# 清洗分块实际验收（2026-09-16）

## 边界与结论

当前主检出、本机 Docker desktop-linux、原卷 `enterprise_agent_postgres18_data`。恢复前只读确认 PostgreSQL 18 集群，恢复后检查已有数据；没有重新初始化原卷。执行前原应用栈已停止，本轮只恢复 PostgreSQL，不宣称业务 API、真实 ONES、Embedding、Qdrant 或 Agent 检索通过。

通过正式 one-shot Migrator 执行：`head=133 baselined=0 applied=133`。原 head=132，只新增两张派生表。没有修改原七表、权限、历史迁移或导入批次。

| 验收项 | 真实结果 |
| --- | --- |
| 文档 / 当前版本 / 收录 | 各 5,000 |
| 文档关联 | 2,407，未变 |
| 完整分块集合 | 5,000 |
| 片段 | 8,309 = 问题 5,199 + 方案 3,110 |
| 正文拆为多块的文档 | 45；其余 4,955 条正文整体保留 |
| 方案处理状态 | included 3,110；absent 1,890 |
| 证据字符数 | 最小 3、最大 1,200、平均 103.39 |
| 待向量化文本最大字符数 | 1,399（预算 1,800；不是 token 数） |
| 首次提交 | created 5,000、reused 0、failed 0 |
| 再次提交 | created 0、reused 5,000、failed 0 |

只读预检、提交、重放三次一致：

```text
profile_version = ones-text-chunks/v1
profile_hash = edd49b9698781b2e473dfae2fcd3410de631a4ddbcc27468cd55bb35ba55fd35
input_hash = b2cf4c2629c6cff76f35d75115d299d543aa1b5c6a83511ed953d820793b7dea
output_hash = 453e6184c77099648c50bbe19aa30e6c06c34e5dc4107b13c719bd156ca80e3f
```

## 原数据未变

迁移/提交前后分别在 PostgreSQL 内对每行 `to_jsonb(row)::text` 做 SHA256，再按行摘要排序合并后做 SHA256；仅输出表级摘要和计数。以下各表前后完全一致：

| 表 | 行数 | 前后相同的摘要 |
| --- | ---: | --- |
| source | 1 | be39d1026c7a0a1d1db1e71cbadea3ca40108dd1c86085b17c2efd4a19cd9b9e |
| document | 5,000 | e18e70655c4a51af4f4029c51df6eb990762755090717c8e5fd45365499bd301 |
| document_revision | 5,000 | eeb4275eb6905786882bf413f2ca95c743a0aab49a83913ccff1d0ddaee7f38b |
| knowledge_base | 1 | 27d30adfa05aef3defafb3dce0d847f91435c0155c682635c75639c9cd42be6e |
| knowledge_base_document | 5,000 | 45e939d0642053b393d60f9f6c518a682eaf6a13119a4fa6188246a26c1bb9c9 |
| import_run | 1 | e6574f0dbc1bd3ad57650113fa61fd008efcc80360c0cd8d914e759da4363794 |
| document_relation | 2,407 | 92bc291787604f6575b0197150d5c922af0af9351ca334f150908719ed808ae6 |

## 独立 SQL 检查

- 5,000 个集合覆盖 5,000 个不同文档；声明块数之和与实际 8,309 一致。
- 切片错误、空白证据、长度不符/超限、集合块数不符：均 0。
- 过期版本/来源摘要不符集合、缺少当前集合的有效收录：均 0。
- 窗口函数检查非空白缺口、超过 120 字符重叠、顺序号异常、未覆盖尾部：均 0。
- `knowledge` 共 9 张表、104 列，缺失注释均 0。
- 应用提交及重放还逐文档重新计算规则结果，并核对完整存储内容，而非只相信已有摘要。

块长度直方图：1–300 为 7,975；301–600 为 87；601–900 为 125；901–1,200 为 122。

质量标记按**块数**统计，不是文档数：attachments_not_collected 7,824、discussion_not_collected 8,100、images_not_collected 7,568、context_truncated 309、hard_split 34。没有对缺失图片/讨论/附件推断内容。硬切及上下文裁剪不等于原证据截断；证据覆盖检查独立执行。

## 测试与构建

- 新分块及原导入测试先在独立 PostgreSQL 18 实例执行：50 passed。随后增加 profile_hash 篡改拒绝测试。
- migration tier 加资源 schema、Job dispatch schema、runtime cutover、事实源清单、测试分层治理回归：**188 passed，18 skipped**。运行时显式配置隔离知识库测试 DSN，因此本次知识库 PostgreSQL 测试并未跳过；18 条跳过项依赖各自未配置的其他独立环境。
- 边界覆盖：短文、长单行、长日志、长短围栏代码、Unicode、尾部与非空白覆盖、有限重叠、方案占位、上下文裁剪、103 文档分页、新来源/配置版本、事务中途失败恢复、篡改拒绝及收录移除。
- Ruff、MyPy（7 个源码文件）、Compose config、OpenSpec strict 和 git diff --check 通过。
- 构建 15 个相关 Compose 后端服务目标；使用实际镜像确认包含迁移 133。两个 file-processing-worker 服务使用同一个显式镜像 `enterprise-agent/file-processing-worker:docling-concurrency-2`，不能用旧的默认同名镜像代替检查。
- 只更新镜像，不启动整栈。构建/导入检查不代表业务就绪或完整 E2E 验收；无运行中的旧业务容器可用于升级前后运行包比对。
- 已核对测试专用标签后移除本次隔离测试容器及其匿名卷，仅删除合成测试数据；原 PostgreSQL 数据卷保留，服务保持运行。

## 后续

此 change 完成清洗分块，不包含采集、OCR、Embedding、Qdrant、召回率评测或知识库 MCP。下一阶段须明确 Embedding 模型及数据出境边界，验证其 token 预算，再执行向量化；不将本次字符预算或内容覆盖验收称为召回质量证明。

运行方式见 `docs/operations/knowledge-text-chunking.md`。本 change 未自动归档或同步 canonical spec。
