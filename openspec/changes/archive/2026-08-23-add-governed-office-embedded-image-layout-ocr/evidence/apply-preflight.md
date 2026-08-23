# Apply preflight evidence

验证日期：2026-08-21（Asia/Shanghai）

## Confirmed-current

- 前置change `add-governed-docling-file-representations`为58/58；其delta已同步到相关canonical specs，新增`document-file-processing` capability，全量OpenSpec严格校验为26/26通过。
- 仓库活动migration目录的最高版本为`115_expand_file_turn_admission.sql`；本地Compose PostgreSQL的`schema_migration`最高版本同为115，且113、114、115均已登记。
- 当前可分配的候选expand migration为`116`；创建文件前必须再次读取磁盘目录与ledger，若head变化则顺延，不复用、不修改113至115。
- 本change开始apply前工作树为clean。完成任务1.1后出现的dirty文件仅为本次基础验收证据、canonical同步、canonical清单和本change任务状态，不覆盖用户预存的未提交实现。

## Proposal、design与delta复核结果

- 同步后的canonical已接受`docling-text-v1`、`file_processing_run`、`file_representation`、Manifest v4、Markdown-only materialization和Docling隔离边界；本change可以在这些身份上追加能力，不得重新定义或替换它们。
- `docling-layout-ocr-v1`仍是单一完整Profile，不与`docling-text-v1`叠加选择；旧Profile的canonical payload、version和hash必须保持不变。
- target delta与当前canonical没有需要改写的语义冲突：Office原件继续仅用于元数据/保留/交付，Agent只物化最终Markdown；picture asset、`DOCLING_JSON`和`OCR_LAYOUT_JSON`不得进入Manifest或Runtime沙盒。
- 现有Runtime source protocol为1.3，本change不升级Runtime协议；114的execution summary约束和115的file-turn admission语义均保持原样。

## 受影响模块

- Profile与处理领域：`backend/app/modules/document_processing/profile.py`、`domain.py`、`provider.py`、`repository.py`、`service.py`、`worker_service.py`、`file_service_client.py`、`source_validation.py`。
- File Service与文件领域：`services/file_service/app.py`及`backend/app/modules/file_workspace/`下的domain、repository、streaming、quota、lifecycle和manifest边界。
- Publication与Job准入：`backend/app/modules/business_application/`、`backend/app/modules/channel/application/channel_ingress_service.py`、`backend/app/modules/job/`。
- Worker与消息拓扑：`backend/app/modules/message_bus/infrastructure/rabbitmq_file_processing.py`、`backend/app/workers/file_processing_worker.py`。
- Runtime与管理面：`backend/app/python_runtime/mcp_config.py`、`backend/app/modules/admin/application/file_operations_service.py`、`frontend/src/contexts/applications/`及`frontend/src/contexts/operations/`相关页面和测试。
- 部署、运维与验证：`docker-compose.yml`、`.env.example`、`docs/operations/governed-document-processing.md`、Docling合成样本/基准/E2E脚本及对应backend测试。
- Schema事实：新的forward migration、`backend/app/shared/schema_fact_sources.json`及migration/schema覆盖测试；已应用migration不得原地修改。

## 实施保护线

- 每次进入schema、Compose或管理端大块修改前重新执行`git status --short`，发现非本change产生的重叠dirty文件即停止并对账。
- 固定镜像合同探针和离线基准未通过前，不创建116 migration、不扩展Profile registry，也不声称目标能力可用。
- 后续验证只使用合成Office/图片，不保存业务正文、文件名、对象键、OCR文字、坐标或凭据到日志和evidence。
