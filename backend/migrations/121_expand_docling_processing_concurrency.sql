-- Expand controlled Docling concurrency facts. This migration is additive and
-- must not rewrite immutable Profile, Publication, Job, processing run, or
-- Representation facts.

CREATE TABLE document_processing_docling_slot (
  slot_no INTEGER PRIMARY KEY CHECK (slot_no IN (1, 2)),
  state TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK (state IN ('AVAILABLE', 'OCCUPIED', 'QUARANTINED')),
  owner_kind TEXT NOT NULL DEFAULT ''
    CHECK (owner_kind IN ('', 'PARENT_RUN', 'PICTURE_ITEM')),
  owner_id TEXT NOT NULL DEFAULT '' CHECK (length(owner_id) <= 256),
  worker_instance_id TEXT NOT NULL DEFAULT ''
    CHECK (length(worker_instance_id) <= 128),
  lease_expires_at TEXT,
  reason_code TEXT NOT NULL DEFAULT '' CHECK (length(reason_code) <= 128),
  acquired_at TEXT,
  updated_at TEXT NOT NULL,
  CHECK (
    (state = 'AVAILABLE' AND owner_kind = '' AND owner_id = ''
      AND worker_instance_id = '' AND lease_expires_at IS NULL
      AND reason_code = '' AND acquired_at IS NULL)
    OR
    (state IN ('OCCUPIED', 'QUARANTINED')
      AND owner_kind IN ('PARENT_RUN', 'PICTURE_ITEM')
      AND length(owner_id) > 0 AND length(worker_instance_id) > 0
      AND lease_expires_at IS NOT NULL AND acquired_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX uq_document_processing_docling_slot_owner
  ON document_processing_docling_slot(owner_kind, owner_id)
  WHERE owner_id <> '';

CREATE INDEX idx_document_processing_docling_slot_state
  ON document_processing_docling_slot(state, lease_expires_at, slot_no);

INSERT INTO document_processing_docling_slot (slot_no, updated_at)
VALUES (1, CURRENT_TIMESTAMP), (2, CURRENT_TIMESTAMP);

CREATE TABLE file_processing_worker_heartbeat (
  instance_id TEXT PRIMARY KEY CHECK (length(instance_id) BETWEEN 16 AND 128),
  profile_hash TEXT NOT NULL CHECK (length(profile_hash) = 64),
  queue_contract TEXT NOT NULL CHECK (queue_contract = 'file-processing/v1'),
  docling_local_workers INTEGER NOT NULL CHECK (docling_local_workers = 2),
  status TEXT NOT NULL CHECK (status IN ('READY', 'DEGRADED')),
  reason_code TEXT NOT NULL CHECK (length(reason_code) BETWEEN 1 AND 128),
  expires_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_file_processing_worker_heartbeat_expiry
  ON file_processing_worker_heartbeat(expires_at, instance_id);
