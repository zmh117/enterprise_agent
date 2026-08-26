## Context

当前 `adapt_docling_picture_result` 逐个读取 Docling `texts`，但要求每个非空文本项的 `prov` 必须是长度恰好为 1 的对象数组。固定 Docling v1.30.0 的 `ProvenanceItem` Schema 本身包含 `page_no`、`charspan` 和 `bbox`，且 `TextItem.prov` 是数组，不保证只有一个元素。

现场 DOCX 的原 run 已确认 7 个图片 occurrence 中第 5、7 个以 `docling_picture_provenance_invalid` 失败。使用相同图片、固定模型和请求选项进行受控复现后，两张图片各有且仅有一个非空文本项包含两个结构完整的 provenance：字符区间分别为 `[0,7]` 和 `[8,20]`，中间仅隔一个空白字符；两个条目均包含 `bbox` 与 `page_no`。诊断只输出结构和长度，没有输出或保留 OCR 正文，临时图片与 JSON 已清理。

现有 OCR Layout v2 要求每个 block 都有确定文字和 bbox，并禁止猜测、夹断或静默改用坐标。因此修复必须把一个上游文本项安全展开为多个平台 block，同时保持既有单 provenance 结果、资源上限和失败关闭边界。

## Goals / Non-Goals

**Goals:**

- 将具有完整、无重叠 `charspan` 和合法 `bbox` 的多 provenance 文本项确定性展开为多个 OCR block。
- 保持单 provenance 输入的现有输出字节、block ID、reading order、置信度与关系行为不变。
- 在展开后执行 block 上限，并确保相同 Docling JSON、图片与 Profile 始终产生相同结果和哈希。
- 让现场 DOCX 通过新 processing run 达到 7/7 图片可用并从 `PARTIAL` 变为 `SUCCEEDED`，同时保留旧 run 事实。

**Non-Goals:**

- 不接受缺失、空、类型错误或没有可验证字符区间/坐标的 provenance。
- 不合并多个 bbox、不使用其包围盒替代真实分段，也不根据 OCR 文字或几何位置猜测字符归属。
- 不增加图片描述、视觉理解、VLM、外部 OCR 服务、Profile 环境开关或新的模型配置。
- 不改变数据库 Schema、消息契约、外部 API、并发槽位、Docling 容器或既有终态 run。

## Decisions

### 1. 单 provenance 保持原路径，多 provenance 才按 charspan 展开

当 `prov` 只有一个合法对象时，继续使用完整 `text` 和该 provenance 的 bbox，避免改变既有 canonical JSON。只有当 `prov` 多于一个时才进入展开路径。

多 provenance 路径要求每个条目均为对象，`charspan` 为两个非布尔整数，并满足 `0 <= start < end <= len(text)`；按 `(start, end, 原始序号)` 排序后区间不得重叠，每个区间截取的文字必须非空，所有未覆盖字符只能是 Unicode 空白。每个条目的 bbox 继续通过现有 `_normalized_bbox` 校验和坐标转换。

选择按 charspan 拆分而不是合并 bbox，是因为拆分保留上游明确提供的文字—坐标对应关系和布局精度。使用第一个 bbox 会丢失证据；取包围盒会制造跨区域大块并扭曲空间关系；继续一律失败则无法处理 Docling Schema 允许的正常输出。

### 2. 输出顺序和身份由展开后的稳定序列决定

输出顺序首先沿用 Docling `texts` 顺序，同一文本项内部按已校验的 charspan 顺序排列。block ID 使用最终输出序号 `b0001`、`b0002`……，`reading_order` 与该序号一致；现有单 provenance 文档因每个文本项仍只产生一个 block，所以身份保持不变。

每个展开 block 的置信度继续调用现有规则：优先使用文本项级 `confidence`，否则使用对应 provenance 的 `confidence`，v2 均缺失时为 `null`。关系算法只接收最终 block 列表，不增加新的关系类型或推断。

### 3. 上限按原文字与最终 block 两个维度执行

字符上限继续按每个上游非空 `text` 的完整长度累计一次，避免因分段重复计数或通过空白间隙绕过限制。`max_blocks_per_picture` 改为约束最终展开后的 block 数，而不是只检查上游 `texts` 数；一旦下一次展开会超限，整张图片以既有 `docling_picture_block_limit_exceeded` 失败关闭，不发布截断结果。

### 4. 模糊结构继续使用安全错误码失败关闭

`prov` 缺失、非数组、空数组、包含非对象、多段缺失/非法 charspan、区间重叠、越界、存在非空白未覆盖文字时，继续返回 `docling_picture_provenance_invalid` 且不可重试。bbox、原点和置信度错误继续使用既有细分错误码。生产日志、数据库和审计不新增 OCR 正文、charspan 内容或 bbox 内容；回归 fixture 使用合成文字，不纳入现场业务正文。

## Risks / Trade-offs

- [Docling charspan 与 Python Unicode 索引语义出现差异] → 使用中文、ASCII、空白和补充平面 Unicode 的合成用例验证切片覆盖；任何越界、重叠或非空白缺口均失败关闭。
- [多段展开使 block 数超过 Profile 上限] → 在追加每个最终 block 前执行上限，整项失败而非静默截断。
- [block ID 因展开而变化] → 变化只发生在此前必然失败、没有可见结果的多 provenance 图片；单 provenance 的既有输出保持不变。
- [只修单元适配但现场链路仍为 PARTIAL] → 必须重建 Worker、创建新 run，并核对 7 个 picture item、三种 Representation 与最终可读状态；容器健康不作为完成证据。

## Migration Plan

1. 先加入多 provenance 合成回归并确认旧实现以 `docling_picture_provenance_invalid` 失败。
2. 实现确定性展开和最终 block 上限，运行 document processing 相关单元/集成测试及静态检查。
3. 重建并滚动更新两个 `file-processing-worker`；Docling、数据库和消息契约无需迁移。
4. 对现场精确 File Version 使用新 Worker build 创建新 processing run，验证 7/7 图片终态、`SUCCEEDED`、三种 Representation 与可物化 Markdown；旧 `PARTIAL` run 保持不变。
5. 若需回滚，恢复上一 Worker 镜像即可；已发布的新 run 和 Representation 作为不可变历史保留，不回写或删除。

## Open Questions

无。现场两张失败图片均已通过受控复现确认是带完整 charspan/bbox/page_no 的双 provenance 结构。
