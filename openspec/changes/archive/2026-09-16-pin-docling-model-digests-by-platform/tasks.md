## 1. 发布合同与平台选择

- [x] 1.1 为平台别名规范化、双平台映射选择、未知平台失败关闭和环境变量不可覆盖补充回归测试
- [x] 1.2 在共享模型artifact模块中固定OCI index、AMD64/ARM64子manifest和模型目录digest，并提供当前平台选择接口
- [x] 1.3 将完整双平台映射纳入`docling-layout-ocr-v2` canonical payload并更新固定Profile hash

## 2. 运行时与处理事实

- [x] 2.1 更新Docling容器启动校验，按当前平台从发布映射选择期望digest并保留逐文件实算校验
- [x] 2.2 更新File Processing Worker readiness和处理服务，使其校验并记录当前平台选中的模型artifact事实
- [x] 2.3 移除Compose中的`DOCLING_MODEL_ARTIFACT_DIGEST`覆盖入口，并补充固定index/平台映射合同测试

## 3. 运维说明与验证

- [x] 3.1 更新文档，说明双平台固定映射、Profile hash升级、发布验证与禁止现场实算放行
- [x] 3.2 运行目标单元/合同测试、静态检查、Compose配置检查、OpenSpec严格校验和`git diff --check`
- [ ] 3.3 在可用的AMD64与ARM64镜像环境验证固定index对应的模型目录digest，并明确区分本机实证与待发布验收
