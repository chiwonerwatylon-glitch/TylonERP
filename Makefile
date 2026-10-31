.PHONY: install run lint fmt test audit
install:
	pip install -r requirements.txt -e ".[dev]" && pre-commit install
run:
	flask --app main run --debug --port 8080
lint:
	ruff check .
fmt:
	ruff check --fix . && ruff format .
test:
	pytest
audit:
	pip-audit -r requirements.txt && bandit -r app -q -ll
