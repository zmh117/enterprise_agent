-- Keep migration 121 immutable after deployment. This additive follow-up owns
-- the PostgreSQL operator comments for its two new tables and all columns.

SELECT 1;

COMMENT ON TABLE document_processing_docling_slot IS
  'Docling本地执行的两个静态准入槽及其租约状态';
COMMENT ON COLUMN document_processing_docling_slot.slot_no IS '静态准入槽编号，仅允许1或2';
COMMENT ON COLUMN document_processing_docling_slot.state IS '准入槽可用、占用或隔离状态';
COMMENT ON COLUMN document_processing_docling_slot.owner_kind IS '占用槽的父运行或逐图任务类型';
COMMENT ON COLUMN document_processing_docling_slot.owner_id IS '占用槽的冻结工作身份';
COMMENT ON COLUMN document_processing_docling_slot.worker_instance_id IS '最近持有租约的Worker不透明实例身份';
COMMENT ON COLUMN document_processing_docling_slot.lease_expires_at IS '当前准入租约失效时间';
COMMENT ON COLUMN document_processing_docling_slot.reason_code IS '隔离槽的安全原因码';
COMMENT ON COLUMN document_processing_docling_slot.acquired_at IS '当前工作身份首次取得槽的时间';
COMMENT ON COLUMN document_processing_docling_slot.updated_at IS '准入槽最近状态更新时间';

COMMENT ON TABLE file_processing_worker_heartbeat IS
  'File Processing Worker短期就绪心跳与冻结执行契约';
COMMENT ON COLUMN file_processing_worker_heartbeat.instance_id IS 'Worker启动时生成的不透明实例身份';
COMMENT ON COLUMN file_processing_worker_heartbeat.profile_hash IS 'Worker代码内冻结的文档处理Profile哈希';
COMMENT ON COLUMN file_processing_worker_heartbeat.queue_contract IS 'Worker消费的冻结安全消息契约';
COMMENT ON COLUMN file_processing_worker_heartbeat.docling_local_workers IS 'Worker期望的Docling本地执行并发';
COMMENT ON COLUMN file_processing_worker_heartbeat.status IS 'Worker就绪或降级状态';
COMMENT ON COLUMN file_processing_worker_heartbeat.reason_code IS 'Worker就绪聚合的安全原因码';
COMMENT ON COLUMN file_processing_worker_heartbeat.expires_at IS '心跳失效时间';
COMMENT ON COLUMN file_processing_worker_heartbeat.updated_at IS '心跳最近更新时间';
