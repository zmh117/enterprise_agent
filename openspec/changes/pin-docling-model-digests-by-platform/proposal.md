## Why

当前 Docling 基础镜像固定的是多架构 OCI index，但仓库只固定了一份由 ARM64 子镜像模型目录计算出的 artifact digest。AMD64 环境会从同一 index 选择不同子镜像并得到另一份稳定摘要，导致部署人员必须现场实算并用 Compose override 放行，造成运行时实际模型与 Profile 声明不一致。

## What Changes

- 将 Docling 基础镜像的多架构 index、AMD64/ARM64 子镜像 manifest 与对应模型 artifact digest 固定为一份代码发布的平台映射。
- Profile canonical payload 固定完整的平台映射；同一发布版本在所有受支持平台使用同一个 Profile hash，运行时只选择本机平台对应条目。
- Docling 启动校验从受信发布映射选择期望 digest，继续逐文件实算用于验证，但禁止把现场实算结果反向作为放行配置。
- CI/发布校验覆盖两个受支持平台；只有升级基础镜像或模型内容时才重新采集、评审并发布 digest 映射。
- 未知平台、子镜像 manifest 漂移、平台条目缺失或模型摘要不匹配时失败关闭。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-file-processing`: 将单一模型 artifact digest 扩展为 Profile 固定的按平台摘要映射，并约束运行时平台选择与验证。
- `platform-operations`: 将 Docling 固定镜像要求扩展为 index 与受支持平台子 manifest 的共同固定，并禁止部署现场覆盖摘要放行。

## Impact

- 文档处理 Profile canonical payload/hash、模型 artifact 校验器和 File Processing Worker 的 Profile 解析。
- Docling Compose/Docker 构建参数与启动校验。
- AMD64、ARM64 镜像合同测试、模型摘要验证及运维文档。
- 当前 Profile hash 将因 canonical payload 升级变化一次；已有运行与 Publication 仍按不可变历史事实解释，新发布使用新 hash。
