# 验收记录：2026-09-13 至 2026-09-14

## 当前结论

**2026-09-14 已在实际运行库 enterprise_agent 的新 knowledge schema 完成正式入库。**
正式 Migrator 仅应用 131，相关服务镜像同步更新，API `/api/ready` 返回 HTTP 200、ready、schema_head=131。
5,000 条缺陷全部入库，重复导入返回同一批次且无新增文档、版本、收录或关联；OpenSpec 9/9 任务完成。
未修改 Agent 发布、角色授权或业务配置；没有下载图片、OCR、Embedding、Qdrant 或实时 ONES 调用。

上轮因旧服务严格检查 head 而暂停，正式库维持 130；用户本轮明确要求“正式入库”后，
按已说明的部署影响完成镜像准备、迁移和必要服务更新。下方区分隔离试验与实际运行库证据。

## 输入预检（仅结构统计）

- 目录：`知识库/数据/5000条完整数据`。
- 详情/list 各 5,000 条；UUID 无重复，ID 集合完全一致，覆盖 25 个项目。
- 所有主记录按照用户声明导入为缺陷；sample 不重复入库。
- 2,407 条来源关联观察；7,798 个图片引用；没有下载/OCR/Embedding/外部 ONES 调用。
- 安全清洗统计为各规范化表示累计匹配次数，不等于含秘密的缺陷数量：
  凭据样式行 285、凭据样式 token 70、URL 1,898、内嵌数据 1。
  不输出或记录匹配原文；这些数字不证明已发现所有敏感数据。
- 原始输入文件没有修改；输出文档/日志不包含原始缺陷正文、URL、真实凭据或业务外部 ID。

## 隔离 PostgreSQL（真实运行）

使用独立 PostgreSQL 18 临时容器，不连接实际运行库。
通过正式 Migrator 从空库迁移到 131，存在 7 张 knowledge 表、78 个字段，表和字段中文注释完整。
验证了 JSONB、带时区时间、跨文档版本指针外键、精确关联目标身份外键、并发来源锁和迁移重放。

5,000 条真实输入经过相同安全预检/清洗后进行完整试导入，第一次结果：

| 核验项 | 数量 |
| --- | ---: |
| 缺陷文档 | 5,000 |
| 内容版本 | 5,000 |
| 知识库收录 | 5,000 |
| 当前内容 hash 与输入一致 | 5,000 |
| 原始关联观察 | 2,407 |
| 目标已解析 | 52 |
| 目标未导入、保留外部引用 | 2,355 |

第二次执行同一批次返回 `replayed=true`，所有上述数量不变，无重复版本或关联。
试导入不是实际运行库验收；该临时容器及其匿名数据卷在测试结束后清理。

## 自动化验证

- `test_suite_tiers.toml` 的 migration 全层，以及 governed resource schema、job dispatch schema、runtime v1.4 cutover preflight：
  **151 passed, 18 skipped**。跳过的是未配置专用环境的既有 PostgreSQL 集成测试；
  新增知识库 PostgreSQL 测试已显式配置隔离实例并实际执行。
- `test_knowledge_import.py` 覆盖字段映射、安全清洗、错误类型/时间单位、重复键/文档/字段、输入集合/数量、
  超限行、幂等、多知识库收录、更新/旧版本、同源时间冲突、中断恢复、禁用文档不恢复、未解析目标补齐。
- Ruff：通过。
- MyPy：7 个涉及实现文件通过。
- `docker compose config --quiet`：通过。
- `git diff --check`：通过。
- `openspec validate import-ones-knowledge-text-foundation --strict --no-interactive`：通过。
- 同步调整现有依赖当前迁移 head 的测试断言为 131；历史迁移文件未改动。
- 正式部署前再次执行 knowledge import、schema migration runtime、schema fact source 三组测试：
  **77 passed, 1 skipped**；本轮未重新创建隔离实例，因此该次跳过知识库专用 PostgreSQL 测试。
  该测试及全量真实样本的隔离验收已在上一轮实际执行；本轮另完成了下方实际运行库验收。

## 实际运行库部署与验收（2026-09-14）

- 数据库：`enterprise_agent`。
- 部署前：head=130、knowledge 表数=0，API ready；Agent Job 与文件处理非终态数量均为 0。
- 镜像使用现有依赖缓存构建；逐项比较 API、Agent Worker、tool-mcp、ones-mcp、dingtalk-mcp、
  File Service、File Processing Worker 的已安装包版本，与切换前运行容器差异为 0。
  首次带自定义 build 参数的候选构建触发了浮动依赖升级，**该候选未部署**，最终使用无依赖差异的重建镜像。
- one-shot 执行：`docker compose run --rm --no-deps migrator python -m app.cli.migrate --build knowledge-import-20260914`。
  结果：`head=131 baselined=0 applied=131`。没有执行附带 bootstrap、发布或授权命令。
- 使用 `docker compose up -d --no-deps --no-build --wait` 更新 14 个服务：api-server、agent-worker、
  job-dispatch-worker、delivery-dispatch-worker、webhook-worker、channel-dispatch-worker、file-worker、
  file-processing-worker、file-processing-worker-2、tool-mcp、ones-mcp、dingtalk-mcp、external-action-worker、file-service。
  不重启 PostgreSQL、RabbitMQ、MinIO、Docling、DingTalk Runtime 或 Python Agent Runtime。
- 新建 knowledge 表数=7、字段数=78，表和字段中文注释全覆盖；schema 对 PUBLIC 的授权项数=0。
- 按运行文档命令只读挂载原始目录，执行 importer `--commit`，结果 `completed`。
- 批次 ID：`fbe4444d-ba8f-5ac6-b0d3-04e32153f91e`。
- 来源 code：`ones-offline-export`，知识库 code：`ones-defects-offline`；来源未确认、知识库仅存储。
- 第二次执行同一 CLI：`replayed=true`，返回同一批次，当前内容 hash 与输入匹配数仍为 5,000。
- 独立 SQL 汇总验收：25 个项目、5,000 个唯一外部 ID；非缺陷/非 active/无效版本指针/空标题正文均为 0；
  7,798 个图片引用，附件仍未采集、OCR 仍未请求。
- 验收后 API `/api/ready`：HTTP 200，`ready`，schema_ready=true，schema_head=131。
  Compose 所有原有服务均保持 running，声明健康检查的服务均 healthy。

| knowledge 表 | 实际记录数 |
| --- | ---: |
| source | 1 |
| document | 5,000 |
| document_revision | 5,000 |
| knowledge_base | 1 |
| knowledge_base_document | 5,000 |
| import_run | 1 |
| document_relation | 2,407 |

其中 52 条关联目标解析到本批文档，2,355 条保留未导入目标的外部引用；并未制造关联工单/需求正文。
重复导入后上述表数量不变。运行批次 processed_count=created_count=5,000，revised_count=stale_count=0，error_code=NULL。

## 范围与后续

代码未提交或推送，变更未自动归档或同步 canonical spec。
服务健康不替代消息/ONES 端到端业务验收，本轮没有触发真实模型、ONES 查询或发送业务消息。

本阶段不包含知识库 Web 配置、角色授权、MCP 检索、定时同步、OCR、分块或 Qdrant；
来源实例/团队身份仍为 `offline_unverified`，后续在线接续必须显式确认。
