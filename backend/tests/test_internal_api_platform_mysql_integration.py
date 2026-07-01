from __future__ import annotations

import os
import unittest

from app.modules.internal_api_platform.domain.addressing import ResourceBinding
from app.modules.internal_api_platform.domain.sql.analyzer import analyze_readonly_query
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    ResourceKind,
)

_RUN = os.getenv("RUN_DB_INTEGRATION") == "1"


@unittest.skipUnless(_RUN, "set RUN_DB_INTEGRATION=1 to run against a live MySQL")
class MysqlIntegrationTests(unittest.TestCase):
    """Opt-in live read-only smoke test.

    Defaults target localhost:3306 root/root db=lims; override via env
    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB / MYSQL_TEST_SQL.
    """

    def test_readonly_select_executes_and_bounds_rows(self) -> None:
        from app.modules.internal_api_platform.infrastructure.db.drivers import MysqlExecutor

        db = DatabaseConnection(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            database=os.getenv("MYSQL_DB", "lims"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", "root"),
        )
        base = Base(code="main", engine=DatabaseEngine.MYSQL, database=db)
        binding = ResourceBinding(
            environment=Environment(code="local", bases={"main": base}),
            base=base,
            kind=ResourceKind.DATABASE,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            database=db,
        )
        sql = os.getenv("MYSQL_TEST_SQL", "SELECT v.* FROM lims.var AS v")
        analyzed = analyze_readonly_query(
            sql, engine=DatabaseEngine.MYSQL, max_rows=5, table_prefix=None
        )
        self.assertIn("LIMIT 5", analyzed.sql)

        result = MysqlExecutor().execute(binding, analyzed.sql, timeout_seconds=10, max_rows=5)
        self.assertLessEqual(len(result.rows), 5)
        self.assertTrue(result.columns)


if __name__ == "__main__":
    unittest.main()
