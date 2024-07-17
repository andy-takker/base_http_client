PROJECT_NAME = base_http_client

develop:
	python3.10 -m venv .venv
	.venv/bin/pip install -U pip poetry
	.venv/bin/poetry config virtualenvs.create false
	.venv/bin/poetry install --all-extras
	.venv/bin/pre-commit install

lint-ci: ruff mypy  ##@Linting Run all linters in CI

ruff: ##@Linting Run ruff
	.venv/bin/ruff check ./$(PROJECT_NAME)

mypy: ##@Linting Run mypy
	.venv/bin/mypy ./$(PROJECT_NAME)
