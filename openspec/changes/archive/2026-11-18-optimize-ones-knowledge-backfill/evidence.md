# 本机工程证据（2026-10-26）

## 范围和未执行事项

仅实现显式创建日补采、现有派生热路径和停采诊断。没有访问真实 ONES、读取真实 Secret/业务正文、修改部署配置、运行目标补采或业务迁移、重启正式服务、提交、推送或归档。工作树已有 Webhook/投递/前端改动均保留；测试分类清单仅增加本任务测试文件。

## 已验证行为

- `once --from-date --through-date` 冻结 backfill 闭区间；拒绝非法、缺项、冲突和缺少初始全量基线。恢复核对原 run 范围，普通 daemon 七日窗口不变，不重新 configure/enable。
- 迁移 150 增加已 INDEXED 清单的 `(index_id, embedding_text_hash)` 部分索引；复用查询使用清单 hash 定位。manifest 每 32 块多行 INSERT 后批查，checkpoint 一条批量 UPDATE，保留逐点冲突、容量和总量校验。
- 同 revision/profile 先读取元数据并验证已有块集的稳定身份、profile、输出 hash、序号/范围和逐块 hash，直接复用；新 revision 才加载来源正文和重新清洗切分。缺块、坏 hash、错误 profile 拒绝，不静默重写。
- 构建和激活仍各自独立完整验证；同次激活按候选及 Qdrant URL/凭据引用去重，不跨目标借用证明。另一目标缺点时整体失败；事务 CAS、资源配置和双重授权边界未改。
- checkpoint 保留日游标并节流写阶段计数、进度时间；health 只读状态及 schema，不加载 Master Key/Provider。陈旧、失败、停用和首次宽限有固定诊断，Compose 每六十秒检查；无新增外部通知服务。已停止容器不会自发健康检查，部署监控仍须订阅 exited/unhealthy 和最近成功时间。

## 合成计数和数据库验证

- 64 文档 / 128 块样本实际清单 SQL 为 **8 次**；原逐块 INSERT+SELECT 按同一规模为 **256 次**，减少约 96.9% 的这部分 SQL 往返。旧值按原实现计算，不是旧分支耗时基准；不能宣称总耗时提升 32 倍。
- 在独立 loopback 随机端口、tmpfs、无业务卷的 PostgreSQL 18 上执行完整新建迁移及五万条合成清单影子表执行计划测试，最终加强断言确认实际命中 hash 部分索引：**1 passed（2.93 秒）**。显式临时测试连接，无密码或真实凭据；临时容器与数据已清理。该测试不是目标环境的执行计划、真实 BGE-M3 吞吐或 ONES 补采验收。

## 回归记录

- 最新补采/恢复/同步 Compose/分块/原子激活专项 **131 passed / 2 skipped（44.21 秒）**；其中新增补采测试单独复测 **31 passed / 1 skipped（18.99 秒）**。跳过包括未配置隔离 PostgreSQL 的用例，不把跳过当通过；上述 PostgreSQL 单独执行补充实际数据库证据。重叠测试不累计。
- 首次知识域扩展 **1082 passed / 37 skipped / 5 failed（334.14 秒）**。五条失败均为未改动 `test_knowledge_online_compose.py` 对 `python-agent-runtime` 的默认服务断言；当前 Compose 默认不启用该 Runtime profile。根 Compose、知识离线/在线 Compose 和该测试文件均不在本任务改动中。未放宽断言或修改 Runtime 部署。
- 最终知识域回归（显式排除已确认无关的五项 Runtime 断言）：**1088 passed / 38 skipped / 5 deselected（341.14 秒）**。新增测试最后复测仍 **31 passed / 1 skipped（18.26 秒）**；真实 PostgreSQL 用例另执行如上，不重复累计。
- 迁移目录显式清单已同步当前 148/149 和本次 150；迁移/事实源/Compose Migrator 专项 **60 passed / 3 failed（21.81 秒）**。剩余一条是并行业务 migration 引入 public 列后旧数量断言仍为 1777、实际 1778（150 只建索引，不新增列），两条仍为旧 `python-agent-runtime` 服务名断言。本任务不更改这些业务列或 Runtime 部署，也不声称全部 CI 通过。
- Ruff、格式、14 个实现文件严格 MyPy、严格 OpenSpec、Markdown 链接和差异空白检查通过。8 项实现与测试任务及本机交付完成，整体 **9/10**，目标环境真实验收保持未完成，不将旧变更的真实环境任务补勾。

## 部署边界

需在授权维护窗口执行统一迁移（包含 150）并同步升级校验 schema head 的配套服务、重建同步镜像和容器。旧临时二十天且仍标记 recent_seven_days 的活动运行，先沿原 manifest 和原无日期 once 恢复，不强改为 backfill，不删除旧索引/卷。本轮依然整代物理复制，真正 O(增量) 的向量存储不在范围；目标环境执行计划、耗时对照、真实补采和监控接入保持待验收。
