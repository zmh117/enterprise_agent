# 模型可见 Capability 描述与管理端版本备注分离

API Capability Revision 必须提供业务 `description`，说明用途、适用场景和返回内容；Agent 配置、应用配置均展示该字段，并将其作为模型 Tool 描述。Capability Release 可以提供可选 `release_note`，说明本次修改、替代关系或运维注意事项，只在管理界面展示，不进入模型上下文、Tool 定义或运行时提示。这样既满足配置界面的备注需求，又避免模型把发布说明误解为调用指令。
