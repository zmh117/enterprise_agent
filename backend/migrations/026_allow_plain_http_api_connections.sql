ALTER TABLE api_connection_draft
  RENAME COLUMN allow_insecure_local_http TO allow_plain_http;

ALTER TABLE api_connection_revision
  RENAME COLUMN allow_insecure_local_http TO allow_plain_http;
