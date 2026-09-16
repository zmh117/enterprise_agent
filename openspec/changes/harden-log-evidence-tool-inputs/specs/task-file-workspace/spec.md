## ADDED Requirements

### Requirement: 日志扫描输入容错不得扩大沙盒权限与预算
`scan_log_evidence` SHALL 在原始词项数量、长度和总 UTF-8 字节预算内按 `casefold()` 去重，保留首次出现的词及顺序；声明与执行 MUST 一致接受合规重复词。工具说明 MUST 明确仅使用当前 Job 精确物化的 `inputs/` POSIX 相对 LOG 路径，路径校验 MUST NOT 自动补全裸文件名或放宽越界限制。

#### Scenario: 大小写与完全重复关键词
- **WHEN** 合规 `literal_terms` 同时包含 `ERROR`、`error`、`ERROR`、`WARN`、`warn`
- **THEN** 工具使用去重后的 `ERROR`、`WARN` 完成一次扫描，与显式去重请求得到一致规范化参数和证据结果

#### Scenario: 重复词不能绕过预算
- **WHEN** 原始数组超过 32 项或 4096 UTF-8 字节，即使去重后低于上限
- **THEN** 工具仍以输入错误拒绝，不扫描文件

#### Scenario: 非法路径提供纠正提示而不猜测
- **WHEN** 输入裸文件名、绝对路径、反斜杠路径、路径穿越或非 LOG 扩展名
- **THEN** 工具拒绝并返回稳定路径错误及固定中文提示，要求使用物化结果中的 `inputs/` 路径；不得自动选择另一个文件

#### Scenario: 错误提示不泄露输入
- **WHEN** 输入包含敏感路径、关键词或日志片段
- **THEN** 工具的安全错误提示仅包含固定规则及示例，不回显这些内容
