## 1. DOCX兼容规范化

- [x] 1.1 在现有文档源模块实现有界的 WPS `../NULL` 零尺寸图片占位识别与临时ZIP规范化
- [x] 1.2 在父文档首次提交 Docling 前接入规范化，并保持恢复已有外部task的路径不变

## 2. 处理器身份与部署

- [x] 2.1 更新 processor version/build digest 与运维说明，保持 `docling-layout-ocr-v2` Profile hash不变

## 3. 回归验证

- [x] 3.1 增加合成DOCX测试，覆盖安全规范化、可见NULL图片拒绝、无目标瑕疵不改写和Worker提交行为
- [x] 3.2 运行目标测试、Ruff、OpenSpec严格校验、Compose配置校验和`git diff --check`
