Use this skill when cache state may explain stale data or inconsistent status.

Rules:
1. Only use approved get or bounded scan operations.
2. Never delete, expire, set, flush, eval, or script Redis keys.
3. Treat cache findings as evidence to compare with database and logs.

