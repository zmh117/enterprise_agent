## Context

当前 File Service 在导入阶段验证 DOCX 的 ZIP 结构、必需包项、宏与展开规模，但不会解析全部 OOXML 关系。`file-processing-worker` 下载精确原件后直接提交给固定 Docling Provider。WPS Office 可能在可见图片之外写入 `Target="../NULL"` 的图片关系，并用零宽或零高 DrawingML 节点引用该关系；LibreOffice会忽略这些不可见占位，Docling 依赖的 `python-docx` 则在加载关系包时失败。

处理 run 的唯一身份包含 source Version、processor build digest 与 Profile hash。直接改变 Profile hash 会让既有 Business Application Publication 快照与代码注册版本不一致，因此兼容算法必须作为新的 processor build 行为交付，而不是修改现有 Profile 身份。

## Goals / Non-Goals

**Goals:**

- 兼容目标为不存在 `NULL` 包项、且全部引用只属于零尺寸 DrawingML 图片占位的 DOCX。
- 保留用户上传原件、File Version、哈希、名称和交付字节不变。
- 用确定、可测试、有展开规模边界的算法生成仅供当前处理 attempt 使用的规范化副本。
- 通过新的 processor build identity 让相同 source Version 可以创建新 run，并保留旧失败 run。

**Non-Goals:**

- 不修复可见图片、正文、表格或其它 OOXML 内容缺失。
- 不接受任意缺失关系、外部关系、加密包、宏文件或结构损坏文件。
- 不增加 LibreOffice、通用 Office 修复器、用户配置项、Provider 扩展点或新的持久化中间文件类型。
- 不自动重写历史终态 run，也不扩大 Agent、MCP、权限或 Sandbox 能力。

## Decisions

### 1. 在现有处理 Worker 内执行单一纯函数规范化

`file-processing-worker` 在下载精确 source bytes 后、首次提交 Docling 前调用现有文档源模块中的一个纯函数。非 DOCX 或无目标瑕疵时返回原始 bytes；匹配时返回内存中的规范化 DOCX。恢复已有 Docling task 时不再次规范化或重新提交。

选择这一位置是因为 Worker 已有受控原件流和 25 MiB 上限，不需要把文件交给新服务，也不会修改 File Service 原件。没有新增 Factory、Manager、Provider 或配置开关。

### 2. 兼容条件必须全部满足

只有以下条件同时满足时才删除关系及其占位节点：

- 关系位于 `word/_rels/document.xml.rels`；
- 类型为标准 OOXML image relationship，且不是 External；
- Target 精确为 `../NULL`，解析后的包项不存在；
- 每个引用都是 `a:blip` 的 `r:embed`；
- 每个引用所在 `w:drawing` 只引用该关系；
- 对应 `wp:inline` 或 `wp:anchor` 的 `wp:extent` 可解析，且 `cx == 0` 或 `cy == 0`；
- 引用数、ZIP成员数与总展开字节不超过现有固定边界。

任何条件不满足时以白名单错误 `docx_null_image_placeholder_unsafe` 非重试失败，不删除内容。关系不存在时不改写包。

### 3. 原件不可变，规范化副本不可持久化

规范化只重写临时 ZIP 中的 `word/document.xml` 与 `word/_rels/document.xml.rels`，其它成员按原顺序和压缩方式复制。规范化 bytes 只作为当前 Docling multipart 输入，不创建 File Version、Representation、对象键或 MCP 内容；处理结束后随内存或 Worker 临时目录释放。

### 4. 保持 Profile hash，更新 processor build identity

`docling-layout-ocr-v2` 的输入输出、OCR选项和资源上限不变，因此保留现有 Profile hash。部署把 processor version 更新为包含 `wps-null-zero-drawing/v1` 的固定版本，并把 processor build digest 更新为覆盖当前 Docling 基础镜像摘要与该规范化算法标识的确定性摘要。新请求由现有唯一约束为同一 source Version 创建新 run；旧 run 和既有 Representation 不变。

## Risks / Trade-offs

- [错误删除可见内容] → 只接受零宽或零高、且 Drawing 内没有其它关系引用的占位；任何不确定结构直接失败。
- [ZIP/XML资源消耗] → 复用现有 25 MiB、20,000成员、200 MiB展开上限，并在解析前检查目标成员大小。
- [规范化改变包字节] → 仅临时副本变化，原件哈希和交付字节保持不变；处理器 build identity区分结果来源。
- [部署后旧失败run被复用] → 更新 processor build digest，使相同 source Version 产生新 run，不修改终态事实。
- [WPS变体超出规则] → 明确失败而非扩展为通用修复器；后续变体必须以独立证据和规格评审处理。

## Migration Plan

1. 发布代码与新的 processor version/build digest，并保持 Profile hash 不变。
2. 先运行合成 DOCX 回归测试和现有文档处理测试，再重建 `file-service` 与 `file-processing-worker`。
3. 新上传文件自动使用新 build；历史失败 source Version 需显式重新请求处理，若当前没有重处理入口则重新上传。
4. 回滚时恢复旧代码和旧 processor build配置；新 build 已产生的 run/Representation作为不可变历史保留。

## Open Questions

无。
