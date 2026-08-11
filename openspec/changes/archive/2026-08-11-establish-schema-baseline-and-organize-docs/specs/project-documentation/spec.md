## ADDED Requirements

### Requirement: 项目文档必须具有单一入口和稳定分类
仓库 MUST 在 `docs/README.md` 提供文档总索引，并 SHALL 将当前文档按 architecture、guides、operations、verification 和 reference 分类；历史材料 MUST 位于 archive 分类，不得与当前操作指引平铺混放。

#### Scenario: 维护者查找当前运行架构
- **WHEN** 维护者从 `docs/README.md` 查找当前系统架构或运行链路
- **THEN** 索引将其导航到 architecture 下的当前文档，并明确该文档的事实范围

#### Scenario: 维护者查找运维步骤
- **WHEN** 维护者查找数据库、Compose、Master Key、钉钉重建或 Runtime 运维步骤
- **THEN** 索引将其导航到 operations 下的可执行 Runbook，而不是历史实施记录

### Requirement: 当前事实、规范意图和历史证据必须明确分层
当前文档 MUST 区分已由代码或运行验证确认的事实、Canonical OpenSpec 规范意图和带日期的验证快照；ADR、旧实施基线和退役组件说明 MUST NOT 被表述为当前能力。

#### Scenario: 旧 API Platform ADR 被保留
- **WHEN** 旧 API Capability、Handler、Connection 或 Resource Mapping ADR 仍有审计价值
- **THEN** 文档移动到 archive 历史区并标记其退役边界，不再出现在当前设计入口

#### Scenario: 验证记录可能过期
- **WHEN** 文档记录一次 Compose、数据库或 Runtime 实际验收
- **THEN** 文档标明验证日期、版本或 head，并不得把该快照自动描述为当前实时状态

### Requirement: 文档移动不得破坏仓库引用
文档重组 MUST 更新根 README、backend README、CONTEXT、OpenSpec artifact、脚本和文档之间的相对链接，并 MUST 提供自动化本地链接检查，拒绝不存在的仓库内 Markdown 目标。

#### Scenario: 文档路径发生移动
- **WHEN** 当前文档或历史 ADR 被移动到新分类目录
- **THEN** 所有仓库内引用同步更新且链接检查通过

#### Scenario: 提交包含失效链接
- **WHEN** Markdown 链接指向不存在的仓库内文件或锚点格式无法解析
- **THEN** 文档质量门禁返回非零状态并阻止将整理工作标记完成
