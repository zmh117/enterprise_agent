## Context

`docling-serve:v1.30.0` 目前以多架构 OCI index digest 固定。该 index 在 Linux AMD64 与 Linux ARM64 上分别解析为不同的子 manifest，镜像内 `/opt/app-root/src/models` 的实际文件集合也具有不同的确定摘要。现有 `docling-layout-ocr-v2` Profile 和 Compose 只固定 ARM64 摘要，导致 AMD64 部署只能现场实算并覆盖环境变量；这样会让同一 Profile hash 在不同环境表达不同模型事实，破坏发布不可变性。

已确认的发布映射如下：

| 平台 | OCI child manifest digest | 模型目录 digest |
| --- | --- | --- |
| `linux/amd64` | `sha256:0ccbc00b5f8b443334a7c4f36a5c6ff89c684c6fbe18ff7c1bc41e00b8e01657` | `sha256:bd9b6624ee97cd02b2506737e6f1646e25c68bf64a1cf4825a2ff69a5992c090` |
| `linux/arm64` | `sha256:b09477515c6234bb86c8a90c9db3af2b5d6991aeb6b64c3348283be264dba63c` | `sha256:9e53a21c25853b53fa0b46df02bb8ebad1d5087dee342d7ef412efecaad0912c` |

两者共同隶属于固定 OCI index `sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`。模型目录摘要算法保持 `relative-path-size-content-sha256/v1`。

## Goals / Non-Goals

**Goals:**

- 让同一代码发布的 Profile 在 AMD64 与 ARM64 上具有相同 canonical payload 和 Profile hash。
- 在代码中唯一固定 OCI index、平台子 manifest 与平台模型目录摘要，消除现场人工覆盖。
- 运行时按规范化后的本机 OS/架构选择精确平台条目，并对模型目录重新计算摘要进行失败关闭校验。
- 让 Worker readiness、处理事实和运维文档都引用实际选中的平台条目。
- 为两个受支持平台提供可复现的发布验证入口。

**Non-Goals:**

- 不支持除 `linux/amd64`、`linux/arm64` 之外的平台。
- 不允许运行时探测结果、环境变量或部署人员输入改变受信映射。
- 不引入 Docker socket、镜像仓库运行时查询或联网下载模型。
- 不改变 OCR 能力范围、模型 revision、摘要算法或业务处理拓扑。

## Decisions

### 1. 一个 Profile 固定完整的平台映射

`docling-layout-ocr-v2` 的 `model_artifact` 将同时包含 OCI index digest、摘要算法以及按规范平台键排序的完整平台映射；每个平台条目包含 child manifest digest 和模型目录 digest。完整映射进入 Profile canonical payload，而不是只放当前机器条目。

这使相同代码在 AMD64 与 ARM64 上产生相同 Profile hash，并让发布审批能够审查两个平台的完整供应链事实。备选的“每个平台一个 Profile”会制造不必要的 Publication 分叉；“Profile 仍存单摘要、运行时环境变量覆盖”则继续破坏不可变性，因此不采用。

### 2. 发布目录是唯一受信来源

平台目录定义在可被业务代码和 Docling 镜像内独立校验脚本共同复用的 Python 模块中。Profile、Worker readiness、处理记录以及容器启动校验均从同一目录选择条目，不复制 digest 字面量。Compose 不再传入 `DOCLING_MODEL_ARTIFACT_DIGEST`。

运行时重新计算模型目录 digest 只用于与发布目录对比；实算值不得被写回配置、Profile 或放行开关。环境中遗留同名变量也不得改变期望值。

### 3. 平台识别规范化且失败关闭

平台键使用 OCI 风格的 `linux/amd64` 与 `linux/arm64`。运行时把 `x86_64`/`amd64` 规范化为 `amd64`，把 `aarch64`/`arm64` 规范化为 `arm64`，并组合实际 OS。未知 OS/架构、缺少平台条目、条目格式错误或模型摘要不匹配时，Docling 与 Worker readiness 均失败，处理请求不得发送。

容器无需也不得访问 Docker daemon 来读取当前 child manifest。child manifest 映射通过发布时的 registry 校验确认；运行时以固定 index 构建所得平台镜像和模型目录摘要共同形成验证边界。

### 4. 处理事实记录实际平台条目

Profile hash 标识完整跨平台合同；具体 processing run / picture item 的 processor/model facts 记录当前平台选中的模型 digest，并在已有字段允许时记录规范平台键。这样审计可以同时回答“使用了哪个跨平台 Profile”与“本次运行实际使用了哪个平台 artifact”，而不会改变业务 API 的模型选择能力。

### 5. 发布验证覆盖 index、两个 child manifest 和两个模型摘要

合同测试校验固定 index 与两条平台映射，Compose 校验确保不存在摘要覆盖变量。发布流程应在原生 runner 或受支持的 buildx/QEMU 环境分别构建并运行摘要校验；只有基础镜像或模型内容升级时，才允许通过评审修改映射与 Profile hash。

本机单平台校验只能证明该平台，不得替代另一平台的发布证据。用户提供的 AMD64 摘要可进入本次映射，但最终上线证据仍需对应 AMD64 镜像校验成功。

## Risks / Trade-offs

- **上游 tag 被重推**：构建始终使用固定 OCI index digest，tag 仅用于可读性；index 不匹配即失败。
- **平台目录再次分化**：分化本身可接受，但每个新值必须作为代码与 Profile 变更评审，不能现场覆盖。
- **Profile hash 升级影响旧 Publication**：新映射必然产生新 hash；通过现有不可变 Publication/processing run 边界完成切换，不把旧 hash 解释为新合同。
- **跨架构验证成本较高**：发布验证会增加镜像拉取与模型目录哈希时间；这是固定大模型 artifact 所需的供应链成本，不能降级为部署时人工实算。
- **平台识别差异**：集中规范化并用单元测试覆盖常见别名，任何未知值失败关闭，避免静默选错条目。

## Migration Plan

1. 发布包含完整平台映射的新代码并生成新的 `docling-layout-ocr-v2` Profile hash。
2. 在 AMD64 与 ARM64 构建/运行固定 index，核对 child manifest 映射和模型目录 digest；保留不含模型内容的摘要证据。
3. 通过现有 Profile/Publication 切换前置检查确认旧处理任务已完成或按既有策略处理，再创建使用新 Profile hash 的 Publication。
4. 删除部署侧 `DOCLING_MODEL_ARTIFACT_DIGEST` override，按平台启动并检查 Docling 与 Worker readiness。
5. 回滚时同时回滚应用镜像与对应旧 Profile/Publication；不得把新旧映射混搭，也不得以现场实算值临时放行。

## Open Questions

无产品规格待确认。AMD64 与 ARM64 发布 runner 的具体承载方式属于部署实现选择，但必须产生两个平台的独立校验证据。
