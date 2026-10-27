-- postgres-only
CREATE INDEX knowledge_vector_reuse_hash_idx
  ON knowledge.vector_index_item(index_id, embedding_text_hash)
  WHERE state='INDEXED';

-- sqlite-only
CREATE INDEX knowledge_vector_reuse_hash_idx
  ON "knowledge.vector_index_item"(index_id, embedding_text_hash)
  WHERE state='INDEXED';
