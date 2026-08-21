# Offline Docling model artifact verification

验证日期：2026-08-21（Asia/Shanghai）

- 固定镜像：`docling-serve:v1.30.0@sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`。
- 目录：镜像内只读离线模型目录`/opt/app-root/src/.cache/docling/models`。
- 清单算法：`relative-path-size-content-sha256/v1`；按相对路径排序，每项输入为`relative_path + NUL + decimal_size + NUL + lowercase_content_sha256 + LF`，再计算整体SHA-256。
- 观测文件数：103。
- 固定模型包digest：`sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c`。
- 该digest已进入`docling-layout-ocr-v1` canonical payload；因此目标Profile hash重新冻结为`261633ba86e2e5db9d271bb5a96ebd7fd2edee330d85ab5bc96dd5e2ad190c5e`。既有`docling-text-v1` payload和hash保持不变。
- 验证只读取镜像内模型文件并输出聚合文件数和摘要，不读取Secret、业务文档、图片、OCR文字或对象位置。

实现门禁必须在启动Docling HTTP服务前复算该清单；目录缺失、空目录、文件读取失败或digest不一致均应直接退出，不得联网下载、忽略或回退模型。

首次在上游容器内做只读探测时记录的候选digest未通过最终自建镜像entrypoint复算，已在任何Publication创建或服务切换前废弃。上述值来自最终镜像`enterprise-agent/docling-serve:v1.30.0-layout-ocr-v1`、相同103文件和同一算法的离线复算，并由启动门禁真实通过。
