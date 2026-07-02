# ╔══════════════════════════════════════════════════════════════════════╗
# ║  AI Trader — Task Runner                                            ║
# ╚══════════════════════════════════════════════════════════════════════╝

.PHONY: help install test lint typecheck clean run format precommit

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────

install: ## Install all Python dependencies
	pip install -r requirements.txt

install-dev: ## Install dev dependencies
	pip install -r requirements.txt
	pre-commit install

# ── Testing ───────────────────────────────────────────────────────────

test: ## Run all tests with coverage
	python -m pytest tests/ -v --cov=agents --cov=core --cov=configs --cov=ai \
		--cov-report=term-missing --cov-report=html:reports/coverage

test-quick: ## Run tests without coverage
	python -m pytest tests/ -v

test-watch: ## Run tests in watch mode
	python -m pytest tests/ -v --looponfail

# ── Linting ───────────────────────────────────────────────────────────

lint: ## Run ruff linter
	ruff check agents/ core/ configs/ ai/ tests/

typecheck: ## Run mypy type checker
	mypy agents/ core/ configs/ ai/ --ignore-missing-imports

format: ## Format code with ruff
	ruff format agents/ core/ configs/ ai/ tests/

check: lint typecheck test-quick ## Run all checks (lint + types + tests)

# ── Pipeline ──────────────────────────────────────────────────────────

run: ## Run the main pipeline (paper mode, 3 iterations)
	python main.py

run-live: ## Run the main pipeline (live mode)
	python main.py --live

run-ci: ## Run pipeline for CI (1 iteration, fail-fast)
	python main.py --iterations 1 --fail-fast

# ── Housekeeping ──────────────────────────────────────────────────────

precommit: ## Run all pre-commit hooks on all files
	pre-commit run --all-files

clean: ## Clean temporary files
	rm -rf .pytest_cache/ .mypy_cache/ __pycache__/
	rm -rf reports/coverage/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete

# ── Docker ────────────────────────────────────────────────────────────

docker-backtest: ## Run backtest via docker compose
	cd freqtrade && docker compose run --rm freqtrade backtesting \
		--config user_data/config_backtest.json

docker-hyperopt: ## Run hyperopt via docker compose
	cd freqtrade && docker compose run --rm freqtrade hyperopt \
		--config user_data/config_backtest.json

# ── Git / Sync ────────────────────────────────────────────────────────

sync: ## Sync with remote (shows status first)
	@echo "=== Git Status ==="
	git status
	@echo ""
	@echo "=== Push to remote? (make push) ==="

push: ## Push committed changes to remote
	git push origin main

# ── Raspberry Pi ─────────────────────────────────────────────────────

sync-rpi: ## Sync project to Raspberry Pi via tar+ssh (runs tests first)
	pwsh -NoProfile -Command "./sync_rpi.ps1"

sync-rpi-fast: ## Sync to Pi without running tests
	pwsh -NoProfile -Command "./sync_rpi.ps1 -Fast"

run-pi: ## Run pipeline on Raspberry Pi
	ssh ai-trader 'cd ~/ai-trader && .venv/bin/python main.py --iterations 1'

test-pi: ## Run tests on Raspberry Pi
	ssh ai-trader 'cd ~/ai-trader && .venv/bin/python -m pytest tests/ -v'

shell-pi: ## Open interactive shell on Raspberry Pi
	ssh ai-trader

# ── SSH Tunnel ────────────────────────────────────────────────────────

tunnel: ## Start SSH tunnel to Freqtrade API (background)
	pwsh -NoProfile -Command "./scripts/tunnel.ps1 -Start"

tunnel-stop: ## Stop SSH tunnel
	pwsh -NoProfile -Command "./scripts/tunnel.ps1 -Stop"

tunnel-status: ## Check SSH tunnel status
	pwsh -NoProfile -Command "./scripts/tunnel.ps1 -Status"

tunnel-restart: ## Restart SSH tunnel
	pwsh -NoProfile -Command "./scripts/tunnel.ps1 -Restart"

open: ## Open Freqtrade dashboard in browser
	start http://localhost:8080
