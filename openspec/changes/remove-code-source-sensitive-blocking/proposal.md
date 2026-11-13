## Why

源码读取按文件名和正则内容拒绝整个文件，导致前端语言资源中的普通密码提示文案也被误判，阻断业务错误与实现逻辑的核验。用户明确要求取消这类拦截，按已授权的源码范围直接查询。

## What Changes

- 取消 Runtime Read、Grep 对源码文件名与内容的敏感启发式阻断。
- 同步取消 SVN 单文件 diff 和提交说明中的同类启发式过滤，避免查询路径行为不一致。
- 保留知识库/环境/版本/路径授权、SVN 跟踪与完整性验证、只读挂载、容量边界及临时文件清理；不新增可配置开关。
- 更新代码问答 Skill、运维说明和回归测试，普通配置名称、语言资源不再被解释为受限内容。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`：授权源码读取与分批搜索不按文件名或敏感词正则拒绝文件，继续明确非文本/容量/扫描预算造成的覆盖缺口。
- `builtin-tool-resource`：授权 SVN 历史说明与单文件差异不按同类启发式规则过滤，继续限制权限范围、版本和返回容量。

## Impact

影响 Runtime 源码读取器、分批搜索、knowledge-sync SVN 历史工具及代码问答 Skill。无需数据库迁移、MCP 工具 Schema 变更或知识库重新索引；部署需更新两个 Runtime 和 knowledge-sync 的镜像，已发布的 Skill 按既有应用发布流程更新。平台连接凭据的基础设施隔离和普通日志的正文隔离不变。
