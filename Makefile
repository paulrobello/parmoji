###############################################################################
# Common make values.
lib    := parmoji
run    := uv run
python := $(run) python
pyright := $(run) pyright
ruff  := $(run) ruff
build := uvx --from build pyproject-build --installer uv

export PYTHONIOENCODING=UTF-8
export UV_LINK_MODE=copy
export PIPENV_VERBOSITY=-1

##############################################################################
# Run the app (no CLI entry; for parity).
.PHONY: repl
repl:
	$(python)

.PHONY: uv-lock
uv-lock:
	uv lock

.PHONY: uv-sync
uv-sync:
	uv sync

.PHONY: setup
setup: uv-lock uv-sync

.PHONY: resetup
resetup: remove-venv setup

.PHONY: remove-venv
remove-venv:
	rm -rf .venv

.PHONY: depsupdate
depsupdate:
	uv sync --upgrade

.PHONY: depsshow
depsshow:
	uv tree

.PHONY: shell
shell:
	$(run) bash

##############################################################################
# Checking/testing/linting/etc.

.PHONY: format
format:
	$(ruff) format src/$(lib)
	$(ruff) format tests

.PHONY: lint
lint:
	$(ruff) check src/$(lib) tests --fix

.PHONY: typecheck
typecheck:
	$(pyright)

.PHONY: typecheck-stats
typecheck-stats:
	$(pyright) --stats

.PHONY: checkall
checkall: format lint typecheck test

.PHONY: pre-commit
pre-commit:
	pre-commit run --all-files

.PHONY: pre-commit-update
pre-commit-update:
	pre-commit autoupdate

##############################################################################
# Package/publish.
.PHONY: package
package:
	$(build) -w

.PHONY: spackage
spackage:
	$(build) -s

.PHONY: package-all
package-all: clean package spackage

.PHONY: test
test:
	$(run) pytest --cov=src/$(lib) --cov-report=term-missing --cov-report=html tests/

.PHONY: coverage
coverage:
	$(run) pytest --cov=src/$(lib) --cov-report=xml tests/

##############################################################################
# Utility.

.PHONY: clean
clean:
	rm -rf build dist $(lib).egg-info

.PHONY: help
help:
	@grep -Eh "^[a-zA-Z_-]+:.+# " $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.+# "}; {printf "%-20s %s\n", $$1, $$2}'
