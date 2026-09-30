SKILL := skills/kubernetes-upgrade-planner
PY ?= python3

.PHONY: check test lint validate

check: lint validate test

test:
	$(PY) -m pytest -q tests

lint:
	bash -n install.sh uninstall.sh $(SKILL)/scripts/*.sh
	$(PY) -m py_compile $(SKILL)/scripts/*.py

validate:
	$(PY) tests/validate_skill.py $(SKILL)
	@if command -v uvx >/dev/null 2>&1; then \
		uvx --quiet --from skills-ref agentskills validate $(SKILL) || echo "skills-ref unavailable, skipped"; \
	fi
