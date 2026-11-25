# 项目约定

- 项目推进过程中，若遇到必要的大改，不需要做旧数据兼容，可以直接删除旧数据。
- 不要默认最小改动，默认选择稳健方案。
- 禁止过度设计，不要给自己挖坑，不要设计难以维护的规格。
- 沟通、提案、设计、需求、任务与验收记录使用简体中文。
- 浏览器测试使用独立配置，结束时只关闭本任务创建的浏览器及辅助进程，不干扰用户的 Chrome。

# OpenSpec

- OpenSpec 由仓库根目录的 npm 锁文件统一管理。在根目录运行 `npm ci` 安装后，从 `browser-extension/` 执行 `npm run openspec -- <命令及参数>` 操作插件规范。
- 插件上下文与中文规则见 `openspec/config.yaml`。OpenSpec、Chrome 扩展和 Web 开发技能共用[仓库根目录的技能目录](../.agents/skills/)。
- 开发依据为 `MES_Browser_Evidence_Collector_Development_Spec.md`；能力现状与尚未完成的验证以相关代码和 `docs/acceptance.md` 为准。
- 中文正文保留 OpenSpec 解析需要的结构标题与 `Requirement`、`Scenario`、`SHALL`、`MUST`、`GIVEN`、`WHEN`、`THEN`、`AND` 等标记。命令、路径、代码标识符不翻译。
- 初始化不会把原开发规格自动转换成已验收的 OpenSpec 主规格；按实际变更维护 `openspec/changes/` 和 `openspec/specs/`。

- Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.
  避免不必要的次要标签和描述。让布局自己说话。
