"""Deployment-owned result transport, not an Agent-facing MCP or arbitrary proxy."""

CODE_RESULT_PATH = "/internal/code-svn/result"
CODE_RESULT_URL = "http://knowledge-sync:8096" + CODE_RESULT_PATH
CODE_RESULT_HOSTS = frozenset({"knowledge-sync", "knowledge-sync:8096"})
