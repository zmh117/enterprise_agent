# Implementation and compatible deployment validation

验证日期：2026-08-21（Asia/Shanghai）

## 原始内嵌图片像素基准

- `docling-layout-ocr-v1` canonical payload固定`RAW_EMBEDDED_MEDIA_AFTER_EXIF`，且`office_display_transform_applied=false`。
- 图片规范化只应用图片文件自身EXIF方向；不解析DrawingML，不应用Office显示层裁剪、旋转或翻转。
- 合成PPTX transform探针固定验证：Office包内源PNG为`1200×800`，显示层上/下各25%裁剪并旋转90度后，Docling referenced artifact仍为原始`1200×800`；该结果作为预期合同而非阻塞。
- 布局Markdown、Runtime提示、管理端能力说明均明确结果可能包含Office页面上已裁掉区域。

## 自动化验证

- Profile hash导入与canonical payload断言：通过。
- Ruff：`backend/app`、`backend/tests`、`services/file_service`及三个布局OCR脚本通过。
- 受影响后端/领域/Provider/Worker/File Service/Publication/Manifest/Runtime/Compose/migration测试：234 passed，18 skipped。跳过项为当前测试命令未提供外部PostgreSQL条件的既有集成分支；migration 100→116已另在隔离PostgreSQL完成原始回放并记录于`migration-116-validation.md`。
- 管理端目标测试：9 passed。
- 管理端生产build：通过；仅保留既有bundle大小告警。
- `docker compose config --quiet`：通过。
- `openspec validate add-governed-office-embedded-image-layout-ocr --strict`：通过。
- `git diff --check`：通过。

## 兼容部署验证

- 部署前运行库migration head：115；布局OCR Publication计数：0。
- 固定Docling镜像：`enterprise-agent/docling-serve:v1.30.0-layout-ocr-v1`；模型artifact digest校验成功。
- migration 116 forward apply成功；既有管理员、Agent及存储凭据均报告preserved。
- 部署后运行库migration head：116；picture asset/occurrence/item三张核心表存在。
- API readiness报告schema head 116及Python Runtime protocol 1.3 ready。
- File Service readiness报告layout Profile registry、layout schema及document processing内部流ready。
- File Processing Worker readiness报告Docling、File Service、model artifact、Profile registry与RabbitMQ全部ready。
- Python Runtime、Docling及全部受影响Compose服务ready/healthy。
- 运行中的Profile hash与模型digest精确匹配代码/Compose冻结值。
- 部署后布局OCR Publication计数仍为0；本次兼容部署没有创建、发布或激活任何Application能力。

## 尚未完成

任务9.7要求的新建验收Publication全链E2E尚未执行。因此当前证据证明schema、代码、镜像、合同和依赖已兼容就绪，不证明业务Application已经获得布局OCR能力，也不授权目标Publication激活。
