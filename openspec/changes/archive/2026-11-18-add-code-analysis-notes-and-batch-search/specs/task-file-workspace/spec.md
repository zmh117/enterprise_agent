## ADDED Requirements

### Requirement: 代码分析笔记和搜索缓存只属于本次执行
Runtime SHALL 在当前随机 Job Sandbox 的 work/notes 保存 Agent 分析笔记，使用既有文本写守卫和配额。源码搜索副本 MUST 由 Runtime 生成，只读且禁止模型直接读取或更改其内部路径；原生 Grep 只经一次性授权使用。所有文件共享 Sandbox 原子文件数/容量预算，不能跨 Job 或 invocation 复用。笔记不是源码证据；缓存只用于定位，不代替原始路径的版本与证据核验。不自动写入 PostgreSQL、Qdrant、File Service 或普通审计正文。

#### Scenario: 搜索调用完成或失败
- **WHEN** 原生搜索结束、拒绝或失败
- **THEN** 清理本批次只读副本并释放占用；失败的准备清理已分配文件；并发准备不能突破总预算

#### Scenario: 执行终态和异常退出
- **WHEN** Job 成功、失败、取消或超时，SDK 已停止
- **THEN** 统一删除本执行笔记及残留缓存，保留独立安全审计和正式问答记录
- **AND** Runtime 异常退出后通过现有恢复扫描清理不再属于活动执行的残留，不删除另一活动 Job 的目录

#### Scenario: 试图扩大笔记权限
- **WHEN** 纯代码 Job 写源码、其他 Job、outputs、inputs、内部搜索副本或通过符号链接逃逸
- **THEN** 写入前拒绝；混合文件 Job 的原有授权仍单独核验，搜索副本始终只读
