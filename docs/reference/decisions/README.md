# Architecture Decision Records

本目录保留历史决策用于审计，但只有下列 ADR 仍是当前规范：

- ADR-0025：ONES User ID、Team 与默认 Team 属于独立外部身份事实
- ADR-0026：ONES 本人绑定使用短时、单次 Verification Challenge
- ADR-0027：切换默认 Team 必须重新验证
- ADR-0031：外部身份面板区分本人自助与管理员治理边界
- ADR-0032：第一版每个内部用户最多一个当前 ONES 身份
- ADR-0039：钉钉应用访问来自路由命中与当前启用用户
- ADR-0042：Job 冻结内部执行主体但不绕过实时撤权
- ADR-0049：钉钉身份按企业建模
- ADR-0050：File Service 是任务文件和 MinIO 的唯一事实入口
- ADR-0051：Publication 与 Job 冻结版本化文本格式策略，LOG 保持只读

ADR-0001—0024、0028—0030、0033—0038、0040—0041、0043—0048 所描述的 API Capability、Handler、API Connection、Resource Mapping、个人 API Token 或旧工具发布平台已经被 `retire-legacy-api-platform-for-mcp` 取代，仅作为历史记录，不得作为新实现依据。

退役 ADR 已移动到 [旧 API Platform 历史区](../../archive/legacy-api-platform/README.md)。

当前工具运行边界以标准 MCP 为准：`Worker -> Python Runtime -> tool-mcp -> Resource`。历史 TypeScript Agent Runtime 事实只读保留。ONES 身份绑定独立于 MCP 和旧 API Platform，不保存用于业务调用的长期 Token。
