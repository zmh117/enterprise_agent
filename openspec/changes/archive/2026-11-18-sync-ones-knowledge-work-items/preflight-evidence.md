# 实施预检记录（2026-09-21）

本记录是当前实施证据，不替代 canonical 或 delta。只进行了本地文件结构/汇总检查、数据库只读查询和合成回归；未正式导入、修改发布/权限、重启服务、迁移数据库或启用同步。原始文本仅由受限解析程序处理，未向终端输出业务正文或凭据。

## 1. 代码和数据库基线

- 工作树实施前仅有本 change 的未跟踪规划文件，没有已修改产品代码。
- 当前磁盘 migration catalog 与运行 PostgreSQL 的 head 均为 `140`；没有修改历史迁移。
- 已核对知识 canonical、当前导入/分块/向量/治理仓储和领域合同。导入、分块、向量读取确实限定 defect；现有 source 级资源摘要会受同源其他 KB 文档影响。
- 合成回归：`.venv/bin/pytest backend/tests/test_knowledge_import.py backend/tests/test_knowledge_chunks.py -q`，结果 **49 passed, 2 skipped**，20.40 秒。跳过的隔离 PostgreSQL 场景未当作通过；该结果不代表真实 ONES 或业务召回验收。

## 2. 输入完整性及分类发现

| 输入 | 详情数量 | 列表数量 | 详情/list 身份差异 | 跨工单/Story 目录重复身份 |
| --- | ---: | ---: | ---: | ---: |
| 全部工单 | 4820 | 4820 | 0 | 0 |
| 全部story | 17388 | 17388 | 0 | 0 |

- 读取器验证了重复 UUID、JSON 键、文件/行/记录边界；详情/list 的标题、编号、创建时间均对应，无空标题；来源时间戳通过现有微秒合同检查。
- 工单来源类型：`MES工单` 4820 条。
- **Story 目录不是单一类型**：`Story` 4244 条、`Sub-task` 13056 条、`演示子任务` 88 条。列表没有现有识别字段中的稳定类型 UUID；不能把详情的显示类型当稳定 UUID。
- 富文本解析后无描述：工单 1 条、Story 目录 12631 条；后者比初步按非空字符串统计的 12627 条多 4 条。该差异是 HTML 文本解析口径，不是丢失记录。
- 现有 defect normalizer 的安全失败汇总：工单 `knowledge_text_empty` 1 条；Story 目录 `knowledge_text_empty` 12492 条、`knowledge_source_identifier_invalid` 526 条。后者均定位到 `list.sprint.uuid`，不涉及文档 UUID；有些错误会先于空正文检查触发，因此错误计数不可直接当成独立缺失集合。
- 后续需核对可选迭代的具体空值形状并增加明确兼容规则，不忽略所有非法标识，也不静默跳过行。

输入摘要：

| 文件 | SHA-256 |
| --- | --- |
| 全部工单/MES工单_all.jsonl | a2cdb9ebd24b5335c88a5b81d018b18f56a87590c578f7085b33135e27e0933d |
| 全部工单/MES工单_list.jsonl | 2d73a4efd96d7f18a6bc0b653ca6035283ce8ae1df671533df6e87c0d7bf9195 |
| 全部story/MES_story_all.jsonl | 036b0ec6110c3e1be1cc5df27607930fe24f1c2e393075755715089ec752f793 |
| 全部story/MES_story_list.jsonl | 8c9f1db2913aa199bdf60820d4e1bc97786e1c12ff73aec2d3d62a156348973d |

这是结构预检证据，不是整体规范化通过或分类已批准。

## 3. 旧缺陷发布兼容接续清单

- 来源：`ones-offline-export`，`offline_unverified`，现有 5000 条文档。
- KB：`ones-defects-offline`，ID `0191dcf1-3eae-5108-b6ef-f6a3df52aee1`，当前 5000 条 included defect 成员。
- 索引：`ones-defects-bge-m3-v1`，`READY`，声明文档数 5000、点数 8309；本次只读 PostgreSQL 索引元数据，未重新逐点验证 Qdrant。
- Embedding profile hash：`595254deaeae70c19815d4b42847cc468790a2742bbdf4b5bd6703cfefcf22f3`。
- Chunk profile hash：`edd49b9698781b2e473dfae2fcd3410de631a4ddbcc27468cd55bb35ba55fd35`。
- 当前仅一条知识资源：`ones_bug`，ID `da325196-7a3d-4b5b-a46e-258cdae5203b`，enabled、配置修订 9、无待保存草稿，已发布资源版本 2。
- 已发布 revision ID：`6bc1a98b-af88-4bbf-9d9f-1aaa1a7b4081`，索引 ID `cada4ac4-d86d-5446-8cb1-e6c9562ffce2`。
- 资源使用显式 PostgreSQL `external` 连接，非敏感标识为 `host.docker.internal:5433 / enterprise_agent`；与本机 PostgreSQL 端口映射一致。未读取凭据明文，未打印凭据引用或完整配置。
- 当前 reader 对显式存储使用配置摘要版本 3，并包含整个 source 的摘要；这是依据现有代码与发布字段识别的合同版本，尚未重新执行完整内容连接、服务与发布验证。
- 正式多类型入库前需对此资源显式完成 KB 范围摘要接续，保留原索引/profile/授权；首版同库激活还需处理显式 external 模式与平台同库写入绑定的身份核验，不得静默换连接或扩展异库写支持。
- 任何实际接续操作前再次核对上述 revision、状态、存储身份及管理员草稿；当前清单不构成已完成发布接续或 MCP 真实验收。

## 4. 分类确认（已解除暂停）

设计原假设离线批次主类型一致，而真实 Story 目录包含三种类型。用户已确认全部三类收录需求知识库，document_kind 为 requirement，保留真实来源子类型，不把子任务改称 Story。已同步设计和 delta，可继续第 2 组。分类批准不代表任何记录已经正式入库。
