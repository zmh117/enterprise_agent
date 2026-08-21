# Docling Office 内嵌图片布局 OCR 上线与回滚

本手册只适用于代码发布 Profile `docling-layout-ocr-v1`。部署 Profile、模型和 schema 不会自动赋予既有 Application 新能力；只有冻结精确 code/version/hash 的新 Publication 才能使用该能力。

## 能力边界

- OCR 使用 Docling 从 DOCX/PPTX 包导出的原始内嵌图片，只规范化图片文件自身 EXIF 方向。
- 不解析 DrawingML，不应用 Office 显示层裁剪、旋转或翻转；结果可能包含页面上已裁掉区域。
- Agent 只读取最终 Markdown，不物化 Office 原件、图片 asset、Docling JSON 或 `OCR_LAYOUT_JSON`。
- 不启用 VLM、远程图片描述、自定义模型、插件、任意 URL 或运行时模型下载。

## 上线前门禁

1. 确认工作区、目标环境和变更窗口，保留未提交改动；不得输出 Secret、JWT、对象键或业务正文。
2. 确认数据库 migration head 为 `115_expand_file_turn_admission.sql`，且目标构建包含 forward-only `116_expand_office_embedded_image_layout_ocr.sql`。
3. 验证 `docling-layout-ocr-v1` 的代码 hash、Compose 配置 hash 和模型 artifact digest 精确一致；模型目录缺失、空目录或 digest 不一致必须停止。
4. 运行 OpenSpec strict、受影响后端/migration/前端测试、前端 build、`docker compose config --quiet` 与 `git diff --check`。
5. 确认没有已创建或已激活的布局 OCR Publication；兼容部署期间历史 `NONE` 与 `docling-text-v1` Publication 必须保持原解释。

## 兼容部署顺序

1. 构建固定 Docling 镜像及受影响的 migrator、API、File Service、File Processing Worker、File Worker、Python Runtime 和 Admin Web 镜像。
2. 先运行 migrator应用 migration 116；禁止删除 migration ledger、逆向 DDL 或把失败迁移标记为成功。
3. 更新 API 与 File Service，再更新 File Processing Worker、File Worker、Python Runtime 和 Admin Web。
4. 验证数据库 head、服务 readiness、RabbitMQ 文档处理拓扑、Profile registry/hash、三种必需输出合同、模型 digest 和 Docling真实健康。
5. 只用不含业务数据的合成 DOCX/PPTX 验证原始图片像素基准、EXIF、软/硬上限、部分成功、重试、assembly 和清理。

容器 running/healthy 只证明进程状态，不替代 Publication→附件入站→parent/逐图/assembly→三种 Representation→Manifest→Runtime Markdown→Agent 回答→原件 Delivery 的新鲜全链验收。

## Publication 激活门禁

1. 新建只用于验收的 Application Revision/Publication，冻结 `docling-layout-ocr-v1` 的精确 code/version/hash；不得改写历史 Publication。
2. 使用合成附件完成新鲜全链 E2E，并确认 Agent 明确说明原始内嵌图片基准、可能包含已裁掉区域和非完整视觉理解。
3. 验证 Office 原件 Delivery 仍交付精确 source Version，布局 Markdown、布局 JSON 和图片 asset 均未获得交付、编辑或物化动作。
4. 仅在全链、清理、隔离、幂等和安全观测全部通过后，才可显式激活目标 Publication。

## 回滚

1. 停止创建或激活新的 `docling-layout-ocr-v1` Publication；将后续业务切换到一个已验证的 `docling-text-v1` 或 `NONE` Publication。不得原地修改历史快照/hash。
2. 排空或安全终结 layout parent、picture item、assembly、staging、outbox 与 cleanup 队列；同一任务不得同时由新旧 Worker 消费。
3. 回退到仍兼容 migration 116 schema 的已验证应用镜像。保留 migration 116、历史 run、Representation、asset/occurrence/item 身份和审计；禁止 down-migrate、删除 ledger 行或把 layout run 解释为 text run。
4. 若 source 已不可用，清理继续失败关闭；不得从已清理 picture asset 恢复或扩大内容访问。

## 立即停止条件

- Profile hash、模型 digest、layout schema 或必需输出集合不一致；
- Docling/Worker 试图联网下载模型或获取对象存储凭据；
- 队列、日志、指标或审计出现文件名、图片、OCR正文、坐标、对象键或凭据；
- Office 显示裁剪/旋转被误报为已应用，或 Markdown/管理端/Runtime 缺少原始图片基准提示；
- 重试产生重复 item、assembly 或 Representation；
- 没有可用的兼容回滚镜像、新鲜全链验收或安全清理证据。
