## MODIFIED Requirements

### Requirement: Tool Manifest 必须声明执行副作用分类
代码 Tool Manifest SHALL 为每个 Tool 声明 `effect=read|mutation` 和 `confirmation_policy`，并 MUST 校验 read Tool 不绑定 mutation 确认策略、mutation Tool 必须绑定代码支持的确认策略。固定业务 MCP Tool 还 MUST 声明非空 operation code、目标策略和 Provider profile；其模型可见名称、描述、输入 Schema 与目标策略 MUST 经过当前固定官方契约清单校验。新 Job 快照 MUST 在既有 input schema hash 之外独立冻结并验证 effect、confirmation policy、operation code、risk level 与目标策略；名称、描述、Schema 或目标语义发生破坏性变化时 MUST 创建新 Agent/Application Publication，历史快照保持原有兼容读取，后续 retry 仍须经过当前代码 Manifest 与既有授权复核。

#### Scenario: 新增 ONES 修改 Tool 未声明确认
- **WHEN** 代码 Manifest 注册 `ones_update_work_item` 但 effect 或确认策略缺失
- **THEN** 启动、发布和 Job 快照校验失败关闭

#### Scenario: 钉钉 Tool 描述与官方目标语义不一致
- **WHEN** 代码 Manifest 使用与官方相同或相似的机器人消息名称，却把目标范围描述为不同能力
- **THEN** Tool catalog 和新 Publication 校验失败关闭
- **AND** 系统不得仅修改提示词绕过契约升级

#### Scenario: 新旧 Publication 的 Tool 合同不同
- **WHEN** 修复后的名称、描述、Schema 或目标策略改变合同 hash
- **THEN** 新 Job 只使用新 Publication 冻结的合同
- **AND** 历史 Job 继续保留原 identifier、hash 和审计事实

