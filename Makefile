.PHONY: check compile format-check lint typecheck test unittest openspec-validate

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
	openspec validate add-readonly-diagnostic-agent-mvp

check: compile format-check lint typecheck test unittest openspec-validate
