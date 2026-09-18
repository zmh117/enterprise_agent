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
