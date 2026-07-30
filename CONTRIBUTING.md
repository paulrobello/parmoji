# Contributing to Parmoji

Thanks for your interest in improving Parmoji. The canonical contributor guide —
project structure, build/test commands, coding style, testing guidelines, commit
and pull-request conventions, and security/configuration tips — lives in
[AGENTS.md](./AGENTS.md). Read it first.

## Quick reference

```bash
make setup          # uv lock + uv sync
make checkall       # format + lint + typecheck + test (run before pushing)
make test           # pytest with coverage
```

- Install pre-commit hooks: `uvx pre-commit install -f` (or `make pre-commit`).
- Keep Pyright and Ruff clean: `make typecheck`, `make lint`, `make format`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
  `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).

## Before opening a pull request

1. Run `make checkall` and confirm it passes.
2. Add tests for new behavior and update docs where the public surface changes.
3. Describe motivation and approach in the PR description and link any issues.

For the full guidelines, see [AGENTS.md](./AGENTS.md).
