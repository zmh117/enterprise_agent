.PHONY: check compile format-check lint typecheck test test-fast test-full test-unit test-contract test-integration test-acceptance test-migration unittest frontend-check openspec-validate schema-baseline-check docs-link-check smoke-db-backed-config

compile:
	python3 -m compileall backend

format-check:
	.venv/bin/ruff format --check .

lint:
	.venv/bin/ruff check .

typecheck:
	.venv/bin/mypy backend/app

test:
	$(MAKE) test-full

test-fast:
	@echo "PR fast suite: unit + contract only; this is not full acceptance."
	.venv/bin/pytest -q --durations=20 -m "unit or contract" backend/tests

test-full:
	@echo "Full local backend regression: all classified tiers; external integrations may skip explicitly."
	.venv/bin/pytest -q --durations=30 backend/tests

test-unit:
	.venv/bin/pytest -q --durations=20 -m unit backend/tests

test-contract:
	.venv/bin/pytest -q --durations=20 -m contract backend/tests

test-integration:
	.venv/bin/pytest -q --durations=20 -m integration backend/tests

test-acceptance:
	.venv/bin/pytest -q --durations=20 -m acceptance backend/tests

test-migration:
	.venv/bin/pytest -q --durations=20 -m migration backend/tests

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
