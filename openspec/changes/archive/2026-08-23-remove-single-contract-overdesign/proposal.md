## Why

`converge-single-current-file-rule` 已把运行合同收敛为唯一当前实现，但实现中仍残留单元素 Registry/Policy、只有一次性调用方的通用扩展点、恒真兼容字段和不可达错误分支；文件域重置还越界承担了 Agent/Application 配置删除。继续保留这些结构会抵消本次收敛的维护收益，并扩大破坏性命令的职责范围。

## What Changes

- **BREAKING** 将开放测试文件域重置恢复为只删除受管对象、文件域事实及其强关联终态 Job/Delivery/Outbox；删除其中对 Agent Definition/Publication、Business Application Revision/Publication、Route、Deployment、Tool/Skill/Channel/Webhook 绑定的识别与删除逻辑。遗留配置只作为 migration 阻断事实报告，不由文件域重置自动处理。
- **BREAKING** 从 readiness `core` 响应删除恒为 `true`、没有真实探针或当前消费者的 `runtime_assembly` 字段。
- 删除无生产调用方的 `file_format_policy_unknown`、不可达的 `file_format_policy_denied`、已移除 `policy_source` 测试输入及通过错误 Python 调用签名验证“无版本选择器”的测试。
- 删除单元素 `TextFormatPolicy`/`get_text_format_policy()` 层，保留固定文本格式定义与按名称、按 code 查询函数。
- 删除单元素 `PROFILE_REGISTRY`，直接解析 `NONE` 或唯一 `docling-layout-ocr-v2` 常量并直接校验其 hash。
- 将 Schema head 例外从“任意 previous heads 集合”收窄为重置命令所需的单个明确 previous head，不提供尚无使用者的多 head 扩展点。
- 删除仅为 `file_get_metadata` 误调用增加的目录二次查询和专用错误码；继续由工具合同指引目录候选直接调用物化工具，未在初始 Manifest 的 metadata 请求统一按既有拒绝返回。
- 收缩提示词和 reset 测试：验证公开业务不变量、稳定工具/错误边界和最终状态，不绑定完整提示文案、私有方法或 SQL 字符串拼接。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`: 明确破坏性文件域重置不得扩展为 Agent/Application 配置清理器，且 readiness 只暴露有真实状态来源的当前字段。

## Impact

- 后端：`file_workspace/open_test_reset.py`、重置 CLI、migration schema head validator、文件格式规则、文档处理 Profile、File Authorization、readiness。
- 测试：开放测试重置、File MCP 工具合同、Agent 文件提示、文本格式规则、readiness 与管理端运行记录 fixture。
- API：删除未规范化且恒真的 `core.runtime_assembly`；其它 File MCP 输入、输出和授权范围不变。
- 数据与部署：不新增 migration，不迁移或删除 Agent/Application 配置；migration 119 继续对遗留引用失败关闭。
