## ADDED Requirements

### Requirement: 数据库压缩字段必须在已授权查询中自动处理

`query_database` SHALL 在 MySQL、SQL Server、Oracle 的驱动取值和结果处理阶段使用代码固定的自动检测规则，不要求 Resource、Agent、Application 或角色新增解码配置，不新增独立 Tool 或开放 Python/CLI 执行能力。检测 MUST 基于本次查询实际取得的值及驱动类型，不依赖 `C_OPTEXT`、源表名、列名或别名白名单。已有 Tool identifier/input schema、Job 冻结合同、实时授权、只读 SQL、表/目录范围和资源唯一解析 MUST 继续生效；解码不扩大数据访问权，也不修改数据库值。

#### Scenario: 三种引擎的 C_OPTEXT 自动处理
- **WHEN** 已授权 SELECT 分别取得 MySQL MEDIUMBLOB、SQL Server VARCHAR(MAX)、Oracle BLOB 中完整且受支持的 zlib 内容
- **THEN** 三种引擎按相同检测规则返回 UTF-8 明文和解码状态
- **AND** 不要求管理员修改资源发布、Agent、应用或角色配置

#### Scenario: 别名和其它字段携带同类压缩值
- **WHEN** 合法查询返回别名列或其他列中的同类受支持值
- **THEN** 系统按实际值识别，返回列名和查询投影保持原有语义
- **AND** 不按名称猜测或新增来源权限

#### Scenario: 工具或数据范围无权
- **WHEN** 当前用户无 Tool grant、Job 未冻结 query_database、授权已撤销或 SQL 目标越界
- **THEN** 既有授权或只读范围校验在 Provider I/O 前拒绝
- **AND** 不因检测到压缩值、已存在文件或管理员身份绕过授权

### Requirement: 自动检测必须验证单个标准 zlib 流与严格 UTF-8

系统 SHALL 识别 `bytes/bytearray/memoryview` 中的原始标准 zlib 流，及字符串或严格 ASCII 字节中的标准 Base64/Hex 包装。Base64 MUST 校验字母表、正确填充及规范化往返；Hex MUST 校验完整偶数字节对，可接受一个明确的 `0x/0X` 前缀。系统 MUST NOT 自动补填充、忽略中间非法字符、猜字符集或解释任意字符串为代码。

进入解压前 MUST 验证 zlib 的压缩方法、窗口和头校验；成功 MUST 同时满足完整流、校验和有效、EOF、无尾随数据和完整严格 UTF-8 解码。第一版 MUST 仅解压一次并保持输出为字符串；raw DEFLATE、gzip、ZIP、URL-safe Base64、外部预置字典和递归解压不得作为自动成功路径。

#### Scenario: 原始字节和两种文本包装
- **WHEN** 候选分别为原始 zlib 字节、规范标准 Base64 或合法 Hex，且完整流解压后是严格 UTF-8
- **THEN** 返回相同明文字符串，输入包装分别标记为 raw_zlib、base64_zlib、hex_zlib
- **AND** 普通 NULL、数字和布尔不参与检测

#### Scenario: 普通长字符串与伪前缀
- **WHEN** 值只是长字符串、普通 Base64/Hex 或带常见压缩前缀但没有有效完整 zlib 流
- **THEN** 不将其当作成功解压内容
- **AND** 普通非候选字符串保持原值；已识别头部的失败候选进入明确回退

#### Scenario: 流损坏、截断或含尾随数据
- **WHEN** 有合法头的候选校验和错误、未到 EOF、拼接多个流或附带额外字节
- **THEN** 标记 invalid_zlib，不返回部分明文，不执行第二次解压

#### Scenario: 预置字典或非 UTF-8 正文
- **WHEN** 候选依赖预置字典，或完整解压后的字节不满足严格 UTF-8
- **THEN** 分别标记 unsupported_dictionary 或 unsupported_text_encoding
- **AND** 不加载外部字典、不回退 GBK/GB18030 或使用替换字符

#### Scenario: 解压结果包含 JSON 或压缩字符串
- **WHEN** 成功明文是 JSON 字符串，或其中还包含另一段压缩包装
- **THEN** 结果仍是单个字符串，不自动变成对象、不继续展开内部字段

### Requirement: 字段解码失败必须保持完整原值的明确表示

已完整取得且能在最终响应预算内容纳的原值 SHALL 在非候选、损坏、字典不支持、文本编码不支持或解压展开超限时保留。字符串 MUST 保持原样；二进制 MUST 采用 `type=binary, encoding=base64, data, size_bytes` 的可逆表示，不能将 `str(bytes)` 或 LOB 对象描述当作正文。成功值 SHALL 返回完整 UTF-8 字符串；系统 MUST NOT 用 NULL、空字符串、部分明文或半个二进制包装冒充成功。

原值无法完整读取或与整条行/诊断一起纳入预算时，系统 MUST 丢弃尚未接纳的整条行、停止后续读取并记录现有 provider_result_truncated；已经接纳的行保持完整。底层读取错误或墙钟耗尽 MUST 使调用安全失败，不返回成功文件。

#### Scenario: 同一行有成功和失败候选
- **WHEN** 一列完整解码成功，另一列流损坏，且原值、成功值和诊断都在预算内
- **THEN** 成功列返回明文，失败列保留原值表示并标记 invalid_zlib
- **AND** 两列均不得伪造空值或丢失失败事实

#### Scenario: 二进制原值回退
- **WHEN** MySQL 二进制或 Oracle BLOB 完整取得但未成功解码
- **THEN** 返回可逆 Base64 二进制表示及准确原始字节数
- **AND** 包装大小计入最终响应，不读取外部对象来恢复内容

#### Scenario: 回退包装或输入无法容纳
- **WHEN** 整个原值不能在输入预算内取得，或 Base64 回退、整条行及诊断超出剩余响应预算
- **THEN** 不接纳该行及其诊断，停止后续读取并标记 provider_result_truncated
- **AND** 不返回局部原值或局部解压内容，不声称查询查全

### Requirement: 压缩字段处理必须服从累计输入展开和墙钟预算

代码 SHALL 沿用 8 MiB 查询容量，限制单字段输入和单次查询累计字符串/二进制原值处理至 8 MiB，并限制单字段及单次查询累计尝试展开至 8 MiB。失败候选已消耗的输入和展开预算 MUST NOT 恢复。解压 MUST 使用分块处理和每次剩余输出上限；最多允许一个只用于确认越界的探测字节，不得保留或返回该字节。剩余预算为零时 MUST NOT 以 `max_length=0` 调用并形成无界解压。

驱动 execute 阶段的取值、Oracle BLOB 读取和解压 MUST 服从当前执行剩余墙钟；原数据库上限仍不超过平台限制与 30 秒中的较小值。应用层 MUST 使用有界行批次，超限后不得继续读 BLOB 正文或在清理时无界排空结果尾部。完整结果及诊断 MUST 共同服从现有行数、最终 MCP 8 MiB envelope 和 Runtime 文件边界；本能力不得提高全局限额。

#### Scenario: 高压缩比或连续失败候选
- **WHEN** 小压缩值展开超过剩余预算，或多个失败候选累计消耗展开预算
- **THEN** 停止当前展开并标记 decode_limit_exceeded
- **AND** 后续候选不获得新展开预算，只能按完整有界原值回退或按行截断

#### Scenario: 展开正好达到边界
- **WHEN** 输出达到剩余上限但仍需确认流是否完整
- **THEN** 系统最多进行一个额外输出字节的有界探测
- **AND** 恰好完整的流可成功，存在额外输出则回退，绝不以零 max_length 开启无界展开

#### Scenario: 执行时间耗尽
- **WHEN** 取值、BLOB 读取或解压期间 execute 墙钟预算耗尽
- **THEN** 当前调用以稳定安全超时语义失败，关闭连接和游标，不发布成功结果文件

#### Scenario: 前面行可用但下一行超限
- **WHEN** 已有完整接纳行而下一行无法容纳
- **THEN** 保留前面完整行，拒绝下一行及其诊断，停止后续获取正文
- **AND** 结果明确 truncated=true，不静默扩大响应上限

### Requirement: Oracle BLOB 必须在有效连接内有界读取

Oracle 驱动 SHALL 只对实际 Oracle 类型信息确认的 BLOB 执行本次字节适配，在连接有效期间先检查大小，再按剩余输入和墙钟预算分块读取。读取所得完整字节 MUST 交给共用检测逻辑；行结果 MUST NOT 保留待连接关闭后读取的 LOB locator。未知具有 read 方法的对象和 BFILE MUST NOT 因自动检测获得读取能力。现有 Oracle 11.2.0.4、匹配架构 Instant Client 19c 和 Thick 边界保持生效。

#### Scenario: BLOB 内存储原始或 ASCII 包装流
- **WHEN** 获准的 BLOB 在输入预算内，分别承载原始 zlib 或其 ASCII Base64/Hex
- **THEN** 连接关闭前读取完整字节，三条路径分别完成检测和解码
- **AND** 输出和诊断不包含 LOB locator 或对象字符串描述

#### Scenario: BLOB 大小超限或读取不完整
- **WHEN** 大小检查发现超限，或实际读取发生错误、未得到声明的完整字节
- **THEN** 超限不读取整个 BLOB 正文并按行截断；读取失败以安全错误终止调用
- **AND** 不把部分字节当作保留的完整原值或成功明文

#### Scenario: 其它可读对象或 BFILE
- **WHEN** 结果包含 BFILE 或不能确认是 Oracle BLOB 的可读对象
- **THEN** 自动解码逻辑不调用其 read 方法、不访问数据库外部文件

### Requirement: 字段解码诊断必须有界且先保护敏感内容

数据库响应 SHALL 在存在候选或二进制回退时提供可选 field_decoding，包含固定 policy_version、候选/成功/失败计数、候选解码完整性及按返回行索引/列名定位的 cells。cell 状态 SHALL 限定为 decoded、invalid_zlib、unsupported_dictionary、unsupported_text_encoding、decode_limit_exceeded、binary_uninterpreted；包装类型和大小 MUST 合法且与实际处理相符。诊断与行 MUST 共同限界和原子接纳，不能在响应外形成无界明细。

现有敏感键规则 MUST 在 BLOB 读取、解压和二进制对象包装前执行，命中字段直接返回 REDACTED；不能用新的对象表示绕过标量脱敏。其余解码明文 MUST 经过现有脱敏后才进入 MCP 返回、受限业务审计和结果文件。普通日志、错误和 Tool timeline MUST 仅保存固定安全状态、大小和计数，不保存压缩值、明文、片段或堆栈。工具输入不能覆盖检测策略或提供字典、代码及执行参数。

#### Scenario: 敏感字段本身是二进制或 BLOB
- **WHEN** 返回字段名称命中现有敏感键规则
- **THEN** 该单元格在包装和解压前变为 REDACTED，Oracle 不读取其 BLOB 正文
- **AND** 不因将值包装为对象而输出原始敏感字节

#### Scenario: 解压后含敏感内容或指令
- **WHEN** 合成的成功明文含敏感键、认证形式文本或指令式内容
- **THEN** 返回及文件正文采用现有脱敏，始终标记为外部不可信数据
- **AND** 普通诊断只含安全事实，不提升为指令或工具权限

#### Scenario: 行查询完整但候选解码不完整
- **WHEN** 查询返回全部有界行，但其中一个识别候选未成功解码
- **THEN** 行覆盖完整性仍按原查询事实表达，field_decoding.complete=false
- **AND** 候选、成功和失败计数与单元格事实一致，不声称失败字段正文已读取

#### Scenario: 旧响应没有解码元数据
- **WHEN** 数据库响应没有 field_decoding
- **THEN** 不推断自动解码已执行或所有字段解码成功
- **AND** 现有普通查询响应仍可按其原合同处理
