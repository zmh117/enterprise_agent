## Why

平台仍同时保留多代文本策略、文档处理 Profile、Manifest 和 Runtime 协议，并为仅用于开放测试的数据维护在线兼容路径，已经造成配置歧义、重复解析链和持续扩大的测试矩阵。开放测试阶段应直接收敛到唯一当前合同，删除旧测试数据和旧实现，在正式数据进入平台前固定最佳规则。

## What Changes

- **BREAKING** 删除 `text-v1` 及 Business Application 中的文件格式策略选择；所有启用任务文件能力的 Publication 固定使用 `text-v2`，普通无文件 Job 也固定使用 Runtime protocol 1.3。
- **BREAKING** 删除 `docling-text-v1` 和 `docling-layout-ocr-v1` 的注册、API 枚举、管理端选项、运行分支及历史解释；文档处理只允许 `NONE` 或 `docling-layout-ocr-v2`。
- **BREAKING** Job File Manifest 只允许 schema v5，Worker 与 Python Runtime 直接传递并校验 v5；删除 Manifest v1-v4 在线读取、hash、投影和测试夹具。
- **BREAKING** Agent Runtime 只允许 `python-v1` protocol 1.3；删除 protocol 1.0、1.1、1.2 的执行合同、生成代码、健康声明和恢复路径。
- **BREAKING** 删除旧附件进程内 DOCX/XLSX/PPTX/Markdown 提取链、`attachment_content` 表及模型上下文中的旧附件正文；所有附件必须进入任务工作区，直接文本由 `text-v2` 处理，Office/PDF/图片只由固定布局 OCR v2 处理。
- **BREAKING** 删除 `agent_job_file_request` 未使用的文档 Profile 字段、TXT/旧配额兼容别名，以及 `message_attachment` 上与 canonical binding 表重复的文件身份影子列。
- 提供显式、破坏性的开放测试文件域重置流程，删除旧文件、表示、处理、Manifest、工作集、附件绑定及其关联终态测试 Job/Delivery/Outbox 数据；不迁移、不回填、不保留旧格式解释器。
- 保留 `NONE` 作为关闭文档处理的状态，保留原始文件/不可变版本、Catalog v5、Working Set、Representation、布局 OCR v2、Sandbox v2 和 Delivery 的当前事实模型。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 固定唯一文本规则、Manifest v5、工作集和附件进入工作区的要求，并删除旧附件解析与旧 schema 兼容。
- `business-application`: 删除文件策略切换和旧文档 Profile，只允许关闭或布局 OCR v2。
- `execution-delivery`: 固定 Python Runtime protocol 1.3 和 Manifest v5 线协议，删除旧协议执行与恢复。
- `platform-operations`: 定义开放测试期破坏性文件域重置、单一合同迁移、依赖清理和验收门禁。

## Impact

- 后端：Business Application、Channel/Job 创建、File Workspace、附件处理、Docling Profile、Agent Worker、Python Runtime、schema contract 与 migration。
- 前端：应用组成配置、API schema、运行状态与测试 Mock。
- 数据库：删除旧文件域测试数据，收缩 Profile/策略/Manifest/协议约束，删除旧表和影子列。
- 契约：`contracts/agent-runtime` 只保留 v1.3，并将文件 Manifest 定义升级为 v5。
- 依赖：`python-docx`、`openpyxl`、`python-pptx` 不再是生产运行依赖；如仅用于测试夹具则移入开发依赖。
- 部署：迁移前必须显式执行开放测试文件域重置；默认 Compose 不提供旧规则回退。
