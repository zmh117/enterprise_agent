# Architecture Decision Records 状态索引

本目录保留 ADR 的历史决策语境，但 ADR 不是当前规范。当前已接受 Requirement 只来自
仓库 `AGENTS.md` 指定的 10 个 canonical specs；实现状态还必须核对代码、migration、
测试和运行证据。

## 与当前实现仍一致

- ADR-0039：钉钉应用访问来自活动路由和当前启用用户。
- ADR-0049：钉钉身份按企业建模，以观察记录关联应用。

## 仅部分仍有效，正文含已失效事实

- ADR-0025/0026/0027/0031/0032：本人 ONES 两阶段绑定、默认 Team 和本人/管理员边界仍在；
  “不保存邮箱/密码/Token 或业务凭据”已失效。当前代码在短时 Challenge 与
  `external_identity_credential` 中使用 purpose-bound AES-256-GCM 加密保存。
- ADR-0042：Job 冻结内部主体且实时撤权仍在；“ONES 不参与 MCP”已失效。当前
  `ones-mcp` 在调用时用 Job Principal 解析当前用户的 ONES 身份和 ACTIVE credential。
- ADR-0050：File Service 作为文件/MinIO 唯一入口仍在；“不部署 Docling”已失效。当前有
  `docling-serve` 与 `file-processing-worker`，但 File MCP 仍内置于 File Service。
- ADR-0051：TXT/LOG/Markdown 操作矩阵仍在；Publication 可选择 `text-v1/text-v2` 已失效。
  当前代码固定 `text-v2`，并拒绝旧 Manifest v1-v4。

上述 ADR 文件顶部已标记状态。阅读历史正文时，状态说明和当前代码/canonical specs
优先；不要从旧措辞恢复兼容分支或未来扩展点。

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
