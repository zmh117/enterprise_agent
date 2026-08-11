.PHONY: check compile format-check lint typecheck test unittest frontend-check openspec-validate schema-baseline-check docs-link-check smoke-db-backed-config

compile:
	python3 -m compileall backend

format-check:
	.venv/bin/ruff format --check .

lint:
	.venv/bin/ruff check .

typecheck:
	.venv/bin/mypy backend/app

test:
	.venv/bin/pytest backend/tests

frontend-check:
	cd frontend && pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test && pnpm build

unittest:
	PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -t .

openspec-validate:
	openspec validate --all --strict

schema-baseline-check:
	.venv/bin/pytest -q backend/tests/test_schema_migration_runtime.py backend/tests/test_initial_admin_bootstrap.py

docs-link-check:
	.venv/bin/python scripts/check_markdown_links.py

smoke-db-backed-config:
	scripts/smoke_db_backed_config.sh

check: compile format-check lint typecheck schema-baseline-check docs-link-check test unittest frontend-check openspec-validate
