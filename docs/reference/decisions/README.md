# Architecture Decision Records 状态索引

本目录保留 ADR 的历史决策语境，但 ADR 不是当前规范。当前已接受 Requirement 只来自
仓库 `AGENTS.md` 指定的 10 个 canonical specs；实现状态还必须核对代码、migration、
测试和运行证据。

## 与当前实现仍一致

- ADR-0039：钉钉应用访问来自活动路由和当前启用用户。
- ADR-0049：钉钉身份按企业建模，以观察记录关联应用。

部分被当前实现取代的 ADR-0025/0026/0027/0031/0032/0042/0050/0051 已从当前参考目录
移除，避免其失效正文被误作现行设计。需要追溯时使用 Git 历史；当前身份、Job、File
Service、Docling 和文本格式规则以 canonical specs、代码和自动化测试为准。

ADR-0001—0024、0028—0030、0033—0038、0040—0041、0043—0048 所描述的 API
Capability、Handler、API Connection、Resource Mapping、个人 API Token 或旧工具发布
平台已经退役，并移动到
[旧 API Platform 历史区](../../archive/legacy-api-platform/README.md)。

当前工具链为：

```text
Worker -> Python Runtime -> tool-mcp -> Published Resource Revision
                         -> ones-mcp -> current user encrypted credential
                         -> File MCP -> File Service
```
