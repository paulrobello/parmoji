# Repository Guidelines

## Project Structure & Module Organization
- `src/parmoji/`: library code — `core.py` (renderer/entry), `source.py` (HTTP/CDN emoji sources), `local_source.py` (filesystem sources + disk cache), `helpers.py` (utilities). Version is defined in `__init__.py`.
- `tests/`: pytest suite. Keep new tests close to the feature under test.
- Tooling: `pyproject.toml` (build and deps), `Makefile` (common tasks), `.github/workflows/` (CI), `ruff.toml`, `pyrightconfig.json`.

## Build, Test, and Development Commands
- Setup env (uses uv): `make setup` (locks + syncs deps). Shell: `make shell` or `uv run bash`.
- Format/Lint/Types: `make format` (Ruff fmt), `make lint` (Ruff check --fix), `make typecheck` (Pyright). All: `make checkall`.
- Tests: `make test` (pytest + HTML coverage at `htmlcov/`), CI XML: `make coverage`.
- Packaging: `make package` (wheel), `make spackage` (sdist), `make package-all`.
- Pre-commit hooks: `uvx pre-commit install -f`; run on demand with `make pre-commit`.

## Coding Style & Naming Conventions
- Python 3.11–3.13 supported; 4‑space indent; line length 120; double quotes by default.
- Linting/formatting via Ruff; docstrings follow Google style; keep modules/functions `snake_case`, classes `CapWords`.
- Type hints required for public APIs; keep Pyright clean (`make typecheck`).

## Testing Guidelines
- Framework: pytest (+ `pytest-asyncio`). Place files as `tests/test_*.py`; name tests `test_<behavior>()`.
- Aim for ≥70% coverage (Codecov range). Prefer fast, deterministic tests; mock network/caching where possible.
- Quick filters: `uv run pytest -k "keyword" -q`.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. Keep subject ≤72 chars; include scope when useful (e.g., `feat(source): add Twemoji vX`).
- PRs must: describe motivation and approach, link issues, include tests and docs updates, and pass `make checkall`. For behavior changes, add before/after notes or small screenshots if rendering is affected.

## Security & Configuration Tips
- Do not commit secrets. Caches write under XDG paths (see README); tests should not rely on network or personal caches.
- Local config lives in `.venv/` and `.tmp/` and is ignored. Use environment variables only in tests when explicitly required.

> Tip: `make help` lists all available tasks.
