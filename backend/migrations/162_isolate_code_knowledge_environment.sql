-- explicit-statements
-- Existing environment-less rows stay NULL and are never eligible for code retrieval.
-- postgres-only
CREATE OR REPLACE FUNCTION knowledge.require_code_environment() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.environment_id IS NULL THEN
    RAISE EXCEPTION 'CODE_ENVIRONMENT_REQUIRED' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.environment_id IS DISTINCT FROM OLD.environment_id THEN
    RAISE EXCEPTION 'CODE_ENVIRONMENT_IMMUTABLE' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
-- statement-end
-- postgres-only
ALTER TABLE knowledge.code_answer ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- postgres-only
DROP TRIGGER IF EXISTS code_answer_environment_required ON knowledge.code_answer;
-- statement-end
-- postgres-only
CREATE TRIGGER code_answer_environment_required BEFORE INSERT OR UPDATE OF environment_id ON knowledge.code_answer
FOR EACH ROW EXECUTE FUNCTION knowledge.require_code_environment();
-- statement-end
-- postgres-only
CREATE INDEX IF NOT EXISTS idx_code_answer_environment ON knowledge.code_answer (source_id,environment_id,svn_revision);
-- statement-end
-- sqlite-only
ALTER TABLE "knowledge.code_answer" ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_answer_environment_insert BEFORE INSERT ON "knowledge.code_answer"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_answer_environment_update BEFORE UPDATE OF environment_id ON "knowledge.code_answer"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE INDEX IF NOT EXISTS idx_code_answer_environment ON "knowledge.code_answer" (source_id,environment_id,svn_revision);
-- statement-end
-- postgres-only
ALTER TABLE knowledge.code_analysis ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- postgres-only
DROP TRIGGER IF EXISTS code_analysis_environment_required ON knowledge.code_analysis;
-- statement-end
-- postgres-only
CREATE TRIGGER code_analysis_environment_required BEFORE INSERT OR UPDATE OF environment_id ON knowledge.code_analysis
FOR EACH ROW EXECUTE FUNCTION knowledge.require_code_environment();
-- statement-end
-- postgres-only
CREATE INDEX IF NOT EXISTS idx_code_analysis_environment ON knowledge.code_analysis (job_id,environment_id);
-- statement-end
-- sqlite-only
ALTER TABLE "knowledge.code_analysis" ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_analysis_environment_insert BEFORE INSERT ON "knowledge.code_analysis"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_analysis_environment_update BEFORE UPDATE OF environment_id ON "knowledge.code_analysis"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE INDEX IF NOT EXISTS idx_code_analysis_environment ON "knowledge.code_analysis" (job_id,environment_id);
-- statement-end
-- postgres-only
ALTER TABLE knowledge.code_qa_record ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- postgres-only
DROP TRIGGER IF EXISTS code_qa_record_environment_required ON knowledge.code_qa_record;
-- statement-end
-- postgres-only
CREATE TRIGGER code_qa_record_environment_required BEFORE INSERT OR UPDATE OF environment_id ON knowledge.code_qa_record
FOR EACH ROW EXECUTE FUNCTION knowledge.require_code_environment();
-- statement-end
-- postgres-only
CREATE INDEX IF NOT EXISTS idx_code_qa_record_environment ON knowledge.code_qa_record (job_id,environment_id);
-- statement-end
-- sqlite-only
ALTER TABLE "knowledge.code_qa_record" ADD COLUMN environment_id TEXT REFERENCES platform_environment(id);
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_qa_record_environment_insert BEFORE INSERT ON "knowledge.code_qa_record"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_qa_record_environment_update BEFORE UPDATE OF environment_id ON "knowledge.code_qa_record"
WHEN NEW.environment_id IS NULL BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_REQUIRED');
END;
-- statement-end
-- sqlite-only
CREATE INDEX IF NOT EXISTS idx_code_qa_record_environment ON "knowledge.code_qa_record" (job_id,environment_id);

-- statement-end
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.environment_id IS '用户明确指定的稳定环境标识，旧空环境记录不得检索或推断归属';

-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_answer_environment_immutable BEFORE UPDATE OF environment_id ON "knowledge.code_answer"
WHEN NEW.environment_id IS NOT OLD.environment_id BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_IMMUTABLE');
END;

-- statement-end
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.environment_id IS '用户明确指定的稳定环境标识，旧空环境记录不得检索或推断归属';

-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_analysis_environment_immutable BEFORE UPDATE OF environment_id ON "knowledge.code_analysis"
WHEN NEW.environment_id IS NOT OLD.environment_id BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_IMMUTABLE');
END;

-- statement-end
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.environment_id IS '用户明确指定的稳定环境标识，旧空环境记录不得检索或推断归属';

-- statement-end
-- sqlite-only
CREATE TRIGGER IF NOT EXISTS code_qa_record_environment_immutable BEFORE UPDATE OF environment_id ON "knowledge.code_qa_record"
WHEN NEW.environment_id IS NOT OLD.environment_id BEGIN
  SELECT RAISE(ABORT, 'CODE_ENVIRONMENT_IMMUTABLE');
END;
