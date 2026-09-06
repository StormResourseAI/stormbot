.DEFAULT_GOAL := help
PYTHON ?= python3
export PYTHONPATH := src
export UNITTEST_RUNNING := 1

.PHONY: help test lint format gate certify policy audit clean

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

test: ## Run the full suite (no network, no dependencies)
	$(PYTHON) -m unittest discover -s tests -t . -b

lint: ## Lint and format-check
	ruff check .
	ruff format --check .

format: ## Apply formatting
	ruff format .

gate: ## Run the release gate under the deployment policy
	$(PYTHON) -m stormbot.assurance.release_gate \
		--policy deployment \
		--format text \
		--output artifacts/release-gate.json \
		--markdown-output artifacts/release-gate.md

certify: ## Run the release gate under the strictest policy (expected to fail here)
	-$(PYTHON) -m stormbot.assurance.release_gate --policy certification --format text

policy: gate ## Apply the CI merge policy to the gate report for uncommitted changes
	git diff --name-only HEAD > artifacts/changed-files.txt
	$(PYTHON) -m stormbot.assurance.ci_policy artifacts/release-gate.json \
		--changed-files-from artifacts/changed-files.txt

audit: ## Verify the lockfiles agree with requirements/dev.in
	$(PYTHON) scripts/check_lockfiles.py

clean: ## Remove generated artifacts and caches
	rm -rf artifacts .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
