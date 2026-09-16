## ADDED Requirements

### Requirement: DOCX兼容规范化必须有界且不改变原件
系统 SHALL 在固定文档处理器build中对 DOCX 执行代码发布的确定性兼容规范化。只有内部图片关系的Target精确为`../NULL`、目标包项不存在、全部引用均为零宽或零高DrawingML图片占位且占位内没有其它关系引用时，系统 MUST 从临时处理副本删除相应占位节点和关系后调用Docling。规范化副本 MUST NOT成为File Version、Representation或可交付原件，且不得改变source Version的字节、哈希、名称、状态或current version pointer。

#### Scenario: WPS零尺寸NULL图片占位
- **WHEN** 合法DOCX包含指向不存在`../NULL`包项的内部图片关系，且该关系的全部引用仅位于零宽或零高DrawingML图片占位
- **THEN** Worker在有界临时副本中删除这些占位节点和关系并继续固定Docling处理
- **AND** 原始DOCX File Version及其内容哈希保持不变

#### Scenario: NULL关系引用可见图片
- **WHEN** `../NULL`图片关系任一引用的DrawingML extent宽高均大于零、无法解析，或同一Drawing包含其它关系引用
- **THEN** 系统以`docx_null_image_placeholder_unsafe`非重试失败
- **AND** 不删除关系、不生成Markdown Representation、不尝试LibreOffice或宽松解析回退

#### Scenario: DOCX没有目标兼容瑕疵
- **WHEN** DOCX不存在符合兼容条件的`../NULL`图片关系
- **THEN** Worker把原始source bytes直接提交给固定Docling Provider
- **AND** 不重写ZIP包或创建兼容中间事实

#### Scenario: 规范化尝试扩大文件边界
- **WHEN** DOCX成员数、展开字节、目标XML大小或规范化结果超过固定处理上限
- **THEN** 系统在调用Docling前安全拒绝
- **AND** 日志、审计和消息不包含文件名、关系值、XML正文或文件字节

## MODIFIED Requirements

### Requirement: 精确源版本产生不可变处理运行
系统 SHALL 为一个精确File Version和一个精确处理器build/Profile组合创建`file_processing_run`。运行 MUST 冻结tenant、source File/Version、processor code/version、覆盖固定Provider镜像与代码发布兼容算法的processor build digest、Profile code/hash和创建来源；状态 SHALL 受控为`QUEUED`、`SUBMITTED`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`PARTIAL`、`NO_TEXT`或`FAILED`，终态运行不得原地重置或改绑到其它源版本。

#### Scenario: 同一源版本重复收到处理事件
- **WHEN** 相同source Version、processor build digest和Profile hash被重复请求
- **THEN** 系统复用同一逻辑processing run或其确定终态
- **AND** 不创建重复的可用表示

#### Scenario: Docling版本升级
- **WHEN** 相同source Version改用新的processor version或processor build digest处理
- **THEN** 系统创建新的processing run并保留旧run及其provenance
- **AND** 旧Job继续使用已经冻结的旧表示

#### Scenario: DOCX兼容算法升级
- **WHEN** 固定Provider镜像不变但代码发布的DOCX兼容算法版本发生变化
- **THEN** processor build digest必须变化并为相同source Version创建新的processing run
- **AND** Profile输入输出、应用发布快照和旧终态run保持不变

#### Scenario: 终态运行被改绑
- **WHEN** 调用方尝试把已终态run改绑到另一source Version或Profile hash
- **THEN** 系统在产生对象或状态副作用前拒绝
