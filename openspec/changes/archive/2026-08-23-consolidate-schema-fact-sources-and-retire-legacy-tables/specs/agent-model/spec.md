## ADDED Requirements

### Requirement: Workflow 草稿图必须只有一个可变事实源
系统 SHALL 将 `agent_workflow_node` 与 `agent_workflow_edge` 的规范化记录作为 Workflow 草稿图的唯一可变事实源；完成兼容切换后，模板记录中的 `graph_json` MUST NOT 参与草稿读取、校验、hash 或发布，也 MUST NOT 继续双写。

#### Scenario: 编辑草稿节点和连线
- **WHEN** 管理端新增、移动、修改或删除 Workflow 节点或边
- **THEN** 系统只更新规范化 node/edge 记录及必要的模板元数据
- **AND** 草稿重新读取后与本次编辑完全一致

#### Scenario: 兼容图副本与规范化记录不一致
- **WHEN** contract 前核对发现模板 `graph_json` 与规范化 node/edge 记录不等价
- **THEN** 迁移失败关闭并输出不含业务配置正文的差异摘要
- **AND** 系统不得根据时间戳或非确定性规则静默选择其中一份覆盖另一份

### Requirement: Workflow 发布快照必须从规范化草稿原子生成
系统 MUST 在一个一致的数据库读取边界内，从模板元数据和规范化 node/edge 草稿生成确定性 graph snapshot、schema version 与 config hash，并 SHALL 将该 snapshot 保存为不可变的已发布运行事实。发布后编辑草稿不得改变历史 snapshot。

#### Scenario: 发布规范化 Workflow 草稿
- **WHEN** 管理端发布通过校验的 Workflow 草稿
- **THEN** 系统从规范化 node/edge 记录生成一个确定排序的不可变 snapshot 和 hash
- **AND** Runtime 后续只读取固定 publication snapshot

#### Scenario: 发布期间草稿并发变化
- **WHEN** 生成 publication snapshot 时草稿 revision 已被并发更新
- **THEN** 系统拒绝本次发布或基于同一已锁定 revision 完整发布
- **AND** 不得产生混合两个 revision 的 snapshot
