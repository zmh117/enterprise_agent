.PHONY: check compile format-check lint typecheck test unittest openspec-validate smoke-db-backed-config

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

unittest:
	PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -t .

openspec-validate:
	openspec validate --specs
	openspec validate connect-internal-tool-platform
	openspec validate add-local-internal-api-platform-loki
	openspec validate stabilize-real-tools-runtime-and-loki-diagnostics

smoke-db-backed-config:
	scripts/smoke_db_backed_config.sh

check: compile format-check lint typecheck test unittest openspec-validate
