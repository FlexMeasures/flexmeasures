---
applyTo: "**"
---
# Pre-commit Hooks

Every commit must pass pre-commit hooks. Committing code that fails pre-commit is a process failure.

## Setup

```bash
uv tool install pre-commit
pre-commit install   # optional: install git hooks locally
```

## Run before every commit

```bash
pre-commit run --all-files
```

All hooks must pass with zero failures before committing.

## Hooks enforced

| Hook | What it checks |
|------|----------------|
| **flake8** | Linting: unused imports, line complexity, style violations |
| **black** | Code formatting (auto-fixes; commit the result) |
| **mypy** | Type annotations (via `ci/run_mypy.sh`) |
| **generate-openapi-specs** | OpenAPI spec generation (local only, skipped in CI) |

## Use the pinned tool versions

The versions in `pyproject.toml` are the ones CI runs, and other versions disagree with them.
A globally installed black from another release formats differently (for instance around multiline strings),
so a file it calls clean can still be reformatted in CI.
Run the hooks through `pre-commit` or `uv run`, which use the pins, rather than a `black` or `flake8` on your `PATH`.

`[tool.uv] required-version` in `pyproject.toml` gates every `uv` command in the checkout (`uv run`, `uv sync`, `uv lock`, and so the hooks too).
With another `uv` version installed, update it to the required one rather than skipping hooks.

## Flake8 configuration

Max line length: 160. Max complexity: 13. Ignored rules: E501, W503, E203.

## Fixing failures

```bash
# Black: auto-fix formatting
black path/to/file.py

# Flake8: fix manually (unused imports, complexity)
flake8 path/to/file.py

# Mypy: add type hints or justified `# type: ignore` comments
ci/run_mypy.sh
```

## openapi-specs hook caution

The `generate-openapi-specs` hook can introduce unintended regressions (version string becoming a dev string, timezone list changing). After running it, inspect the diff and revert any changes that are not motivated by your PR:

```bash
git diff flexmeasures/ui/static/openapi-specs.json
```
