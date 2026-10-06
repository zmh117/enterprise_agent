"""Bounded resource-query data delivered through Job-local result files."""

QUERY_RESULT_TOOLS = frozenset(
    {
        "query_database",
        "query_redis_get",
        "query_redis_scan",
        "query_loki",
        "diagnose_loki_probe",
    }
)
QUERY_RESULT_MAX_BYTES = 8 * 1024 * 1024
DATABASE_MAX_ROWS = 10000

FIELD_DECODING_POLICY = "db-zlib-utf8-v1"
FIELD_DECODING_STATUSES = frozenset(
    {
        "decoded",
        "invalid_zlib",
        "unsupported_dictionary",
        "unsupported_text_encoding",
        "decode_limit_exceeded",
        "binary_uninterpreted",
    }
)
FIELD_DECODING_FORMATS = frozenset({"raw_zlib", "base64_zlib", "hex_zlib", "binary"})
