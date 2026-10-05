.PHONY: dev install test playwright-install

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

playwright-install:
	.venv/bin/playwright install chromium

dev:
	@test -d .venv || $(MAKE) install
	.venv/bin/uvicorn site_lens.main:app --reload --host $${SITE_LENS_HOST:-127.0.0.1} --port $${SITE_LENS_PORT:-8765}

test:
	.venv/bin/pytest -v
