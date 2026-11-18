## Why

已有 5,000 条 ONES 缺陷完成受限文本入库，但尚无可追溯、可重复生成的检索文本块。用户确认先完成清洗分块并在本机实际运行，后续再补采集、Embedding、Qdrant 与 MCP。

## What Changes

- 保留现有 document_revision，在 knowledge 新增 document_chunk_set 与 document_chunk，保存每个来源版本和规则版本对应的一组完整派生结果及其块。
- 增加确定性文本清洗、短文完整保留、长文结构分块、有效解决方案独立分块及带上下文的 embedding_text；不使用模型生成摘要或推断事实。
- 增加只读预检、显式提交和合成演示 CLI；按文档事务保存，重跑复用完整结果，来源更新产生新结果，失败可通过重跑恢复。
- 对现有 5,000 条实际数据生成结果，校验覆盖、长度、来源定位、幂等性和源数据未变，只输出安全统计。
- 不补实时采集，不下载附件或 OCR，不调用 Embedding，不写 Qdrant，不新增 Web/MCP、授权或消息队列。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `platform-operations`：增加受限知识清洗分块与派生结果验收，扩展现有 knowledge schema 治理。

## Impact

- backend knowledge 模块、CLI、下一可用前向迁移、事实源清单、相关测试及中文运行文档。
- 本机 PostgreSQL 原有命名卷已只读验证为现有 PostgreSQL 18 集群；按批准启动后确认 head=132、5,000 个文档/版本/收录及 2,407 条关联，未重新初始化。
- 基础版本与已有业务数据不修改。仅启动必要数据库及一次性任务；不擅自恢复之前停止的整个应用栈。
