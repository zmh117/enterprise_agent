ALTER TABLE browser_answer_delta ADD COLUMN phase TEXT NOT NULL DEFAULT 'answer'
  CHECK (phase IN ('answer','process'));
-- postgres-only
COMMENT ON COLUMN browser_answer_delta.phase IS '公开答复预览或已确认的本轮执行说明';
