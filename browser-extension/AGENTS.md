# 项目约定

- 项目推进过程中，若遇到必要的大改，不需要做旧数据兼容，可以直接删除旧数据。
- 不要默认最小改动，默认选择稳健方案。
- 禁止过度设计，不要给自己挖坑，不要设计难以维护的规格。
- 沟通、提案、设计、需求、任务与验收记录使用简体中文。
- 浏览器测试使用独立配置，结束时只关闭本任务创建的浏览器及辅助进程，不干扰用户的 Chrome。

# OpenSpec

- 本项目在开发依赖中锁定 OpenSpec 2.0.0；执行 `npm run openspec -- <命令及参数>`，避免误用全局旧版本。工作流中示例的 `openspec ...` 也应使用此项目命令入口。
- 项目上下文与中文规则见 `openspec/config.yaml`，官方工作流位于 `.agents/skills/openspec-*/SKILL.md`。
- 开发依据为 `MES_Browser_Evidence_Collector_Development_Spec.md`；能力现状与尚未完成的验证以相关代码和 `docs/acceptance.md` 为准。
- 中文正文保留 OpenSpec 解析需要的结构标题与 `Requirement`、`Scenario`、`SHALL`、`MUST`、`GIVEN`、`WHEN`、`THEN`、`AND` 等标记。命令、路径、代码标识符不翻译。
- 初始化不会把原开发规格自动转换成已验收的 OpenSpec 主规格；按实际变更维护 `openspec/changes/` 和 `openspec/specs/`。

- Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.
  避免不必要的次要标签和描述。让布局自己说话。
