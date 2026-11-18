## ADDED Requirements

### Requirement: 保存问题必须由宿主绑定成功检索
Runtime MUST 在原 invocation 中保留成功代码检索的规范问题，按 search_id 与成功的源码 analysis 关联；保存时 SHALL 使用该关联问题，不依赖模型再次填写相同措辞。服务端 MUST 继续核对问题 hash、Job、环境、来源、版本和实际证据。问题正文不得进入普通安全摘要或日志。

#### Scenario: 保存时模型改写问题
- **WHEN** 模型在保存参数中改写了同一分析的问题
- **THEN** 宿主使用准入所绑定成功检索的规范问题，服务端 hash 校验通过；结论和证据仍独立校验

#### Scenario: 缺失或错误关联
- **WHEN** 未取得成功检索关联、请求其他 analysis 或检索未成功
- **THEN** 拒绝保存，不猜测问题、不绕过服务端校验

#### Scenario: 相同请求重放
- **WHEN** 保存响应不确定且在原有效 invocation 内重放
- **THEN** 使用相同问题、幂等键和内容，沿用既有幂等保存语义
