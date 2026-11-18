# 实施与验证记录

日期：2026-10-27。变更为 `implement-incremental-knowledge-sync`；未提交、推送或部署，保留工作区既有补采、Webhook、Delivery 等改动。

## 已实施

- 迁移 151 登记固定增量索引及每篇文档 PENDING / APPLIED / DONE 断点，并补齐创建日范围查询索引。Schema migration 不执行网络操作。
- 小时同步和明确日期补采切换到 `IncrementalSyncPipeline`。只保存本轮观察对象，按变化文档处理分块、隐藏向量、当前版本和旧块；最多 32 点一批。不调用全库冻结、snapshot、manifest 或 collection 总数检查。
- 无变化文档只更新观察时间，不重新读取正文、分块或写向量。未变更文档不搬运；相同文本向量复用；阶段中断保留结果；单篇失败保留断点并允许其他文档完成。部分失败占用原活动 run，daemon 五分钟后重试。
- 资源发布配置与成员、内容摘要、数量及索引更新时间解耦。保持当前用户 KB 和 ONES 双授权；所有检索路由过滤隐藏点。增量集合受旧代清理保护，离线导入/旧整代同步不得绕过新流程写入。
- 新增 `app.cli.adopt_incremental_knowledge`：默认只读预检，显式 commit 转换已有 READY 索引；不调用 Embedding，保留集合、点 ID 和向量数值。管理员身份、停用绑定、无活动 run、当前模型与 keep_ids 分块、同平台连接和当前资源目标均须通过检查。空的旧索引也必须转换。转换中断可重跑，资源启停和草稿状态保留。
- 停用保留进度，重新启用续跑。已经进入文档派生处理的增量 run 不允许直接 cancel 或修改绑定，避免留下已应用但尚未开放/清理的文档。
- 已同步 `platform-operations`、`builtin-tool-resource` 两份 canonical spec，运行步骤统一维护在 `docs/runbooks/knowledge-ones-hourly-sync.md`。

## 验证结果

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 知识模块、迁移和测试分层回归 | 1164 passed，39 skipped，380.63 秒 | `pytest -q --tb=short backend/tests/test_knowledge*.py backend/tests/test_schema_migration_runtime.py backend/tests/test_test_suite_governance.py`；跳过需单独配置的集成环境 |
| 最终增量专项 | 19 passed，19.60 秒 | 新增三条、无变化、修改、跨库移动、三种外部写入后崩溃、部分失败、发布稳定、资源停用、暂停续跑、旧入口阻断、空库转换、迁移中断、四种查询路由 |
| 隔离 PostgreSQL 18 + Qdrant 1.19.1 与列权限 | 22 passed，11.60 秒 | 新增/修改/隐藏点/提交后崩溃重放、真实 BM25 和 dense 路由、只读角色最小列权限及拒绝；Embedding 和业务输入为合成数据 |
| Mypy | 85 个源文件通过 | knowledge 模块、三个相关 CLI、Knowledge MCP 权限合同 |
| Ruff | lint 与格式通过 | 相关模块、CLI、知识测试和权限合同 |
| Compose | `config --quiet` 通过 | 基础 + knowledge + sync 扩展；另有合成环境的 Compose 回归 |
| OpenSpec | strict 通过 | 本 change 及两个更新的 canonical spec |
| Git | `diff --check` 通过 | 未 stage / commit / push |

空旧索引保护、首次索引登记事务和无变化正文读取的收尾修改已由最终 19 项专项与 22 项隔离验证覆盖。格式调整未改变行为。

隔离测试使用本轮新建的两只容器和临时数据，每次执行后按精确容器 ID 删除；最终按本轮标签检查无残留。未访问或停止用户已有容器、真实 ONES 或真实模型服务。隔离测试入口为 `backend/tests/test_knowledge_incremental_postgres.py`，只接受显式的 `KNOWLEDGE_INCREMENTAL_TEST_POSTGRES_DSN` 和 `KNOWLEDGE_INCREMENTAL_TEST_QDRANT_URL`，限制为本地 `incremental_test` 数据库；权限测试使用已有 `KNOWLEDGE_POLICY_TEST_POSTGRES_DSN` 合同。

回归过程中发现并修正了新增列的只读权限遗漏、CLI 替换后的测试桩、迁移目录及保留数据断言；同时更新了既有 Compose 测试中已过时的单 Runtime 服务名和工作区新增迁移对应的 public 列数预期，没有修改相关部署行为。

## 验收边界

尚未执行目标部署、真实 ONES、真实 BGE-M3 模型或现场几百条补采的耗时验收，任务 4.3 保持未完成。上述结果不能作为容量或固定完成时间承诺。

上线须统一升级至迁移 151 和匹配代码，停止旧同步写者，完成或取消旧整代 run，按手册逐库转换现有索引，再恢复采集。使用独立知识只读账号的环境须刷新新增列权限。转换过程中查询可能短暂失败；单篇更新也允许开放新点前短暂缺失。没有整轮快照回滚合同。


## 2026-10-27 补充：同时间戳直接采用本次内容

用户最终选择直接以本次 B 更新当前 A，取消二次详情复核。此次仅修改在线增量判变，未新增 migration、重试表或额外详情请求；离线导入及旧整代候选的严格规则保持。相同来源时间戳且语义内容/类型不同记为 revised，旧修订及来源时间戳保留；更旧时间戳仍 stale，相同内容仍 unchanged。

在线语义摘要排除归一化版本与采集快照/完整性元数据，保留标题、正文、类型、业务属性、显示名称、编号、创建时间与关联；产品 ID 和关联集合按稳定顺序比较，未知业务数组不重排。候选页面事务提交后输出 `knowledge_source_same_stamp_revised` 的 STAGED 事件，文档向量开放与清理完成后输出 DONE 事件。字段白名单仅含安全 ID、来源时间戳、语义 hash、类型、修订 ID、阶段及固定原因；不输出业务标题、正文、字段值或异常文本。提交与日志间进程退出可能漏日志，以数据库断点为准。

本轮验证：

- 增量、采集、数据库恢复及候选回归：120 passed、2 skipped（62.10 秒）。
- 最终增量专项：32 passed（35.40 秒），包括真实采集服务 + 合成 Provider 的连续三轮流程，确认每单据每轮只有一次详情请求；同戳 B 生效、A 保留、重复 B 零 Embedding/Qdrant 写入、单页事务回滚与幂等重放、元数据差异、业务名称变化、关联变化和分类迁移均覆盖。日志断言确认无合成业务标题/正文。
- 离线类型/导入、创建日补采和测试分层：91 passed、2 skipped（32.35 秒）；包含离线同戳冲突仍拒绝。
- 新建隔离 PostgreSQL 18 + Qdrant 1.19.1：1 passed（4.31 秒），覆盖固定集合、隐藏点、外部写成功后恢复、同戳修订日志、真实数据库关联读取和重复采集幂等。Embedding 与单据为合成输入；两只容器按精确 ID 清理，标签检查无残留。
- Mypy：84 个源文件通过。Ruff lint 与 86 个文件的格式检查通过。
- change 与 platform-operations canonical strict 校验、git diff --check 通过。

首次新增端到端测试使用了与绑定不匹配的合成项目/类型，触发 empty_scope；修正测试输入以严格匹配绑定后通过，未放松生产范围校验。

任务 5.1–5.3 完成；任务 4.3 的真实 ONES/模型/部署验收仍未完成。代码未提交、推送或部署；迁移 151 之后无需额外 DDL，目标环境仍需升级匹配镜像，不能仅 restart 旧代码。对于仍为旧整代模式的环境，先执行既有增量转换流程。


## 本地提交范围复核

提交前仅暂存知识增量同步、同时间戳更新日志及所依赖的补采窗口/向量复用代码、测试和规范。Webhook/Delivery/前端及迁移 148、149 保留在工作区；共享迁移测试和测试分层清单仅暂存知识库相关片段。

将暂存区导出为独立目录，使用该目录的 backend 与测试进行验证，避免未提交的其他改动掩盖依赖：225 项通过、3 项因外部条件跳过；另 1 项 gitignore 检查因临时目录缺少 .git 无法执行，初始化仅临时目录的 Git 元数据后单独复测通过（1 passed）。合计 226 项通过、3 项跳过。提交快照的 Mypy 86 个源文件、Ruff、Compose config --quiet、本 change 和两份 canonical strict 校验均通过。该验证不代表真实 ONES 或生产部署验收。
