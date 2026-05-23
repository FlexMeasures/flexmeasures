---
applyTo: "flexmeasures/**/tests/**/*.py"
---
# Testing Conventions

## Run the full test suite

Before finishing a session and requesting a review, run the complete test suite:

```bash
uv sync --group test
uv run poe test
```

Intermediate full test runs are encouraged when appropriate (e.g., after a significant refactor). During active development, targeted runs (`pytest path/to/test_module.py`) are acceptable.

## Run the full module after changing any test

When you fix or add a single test, always run the entire test module before closing:

```bash
pytest flexmeasures/path/to/test_module.py -v
```

Fixing one test can break adjacent tests in the same module when they share mutable module-scoped fixtures.

## Database fixture selection

| Fixture | When to use |
|---------|-------------|
| `db` | Read-only tests — queries only, no mutations |
| `fresh_db` | Tests that create, update, or delete data |

Using `db` when data is mutated causes `DetachedInstanceError` and flaky cross-test contamination.

## API test isolation

```python
# ✅ Correct: use the requesting_user fixture
def test_my_endpoint(client, requesting_user):
    response = client.get("/api/v3_0/...")

# ❌ Wrong: manually patching _check_token breaks the auth flow
with patch("flexmeasures.api.common._check_token"):
    ...
```

## Test design intent

Before changing a test that fails, investigate whether the test is intentionally designed to catch a production bug:

1. Read what the test is doing and why.
2. Check the production code for the real bug.
3. Only modify a test if you can prove the test design is wrong.

A failing test often reveals a production bug, not a test bug.

## Module-scoped fixture state

Module-scoped fixtures are shared across tests. When modifying shared objects (e.g. `asset.sensors_to_show`), reset them to the column default — not to `None` — in teardown:

```python
# ✅ Reset to column default (empty list)
asset.sensors_to_show = []

# ❌ Reset to None (may cause unexpected ValidationError downstream)
asset.sensors_to_show = None
```

## Authentication failures in tests

If you see unexpected `401 Unauthorized` in tests:
- Check that the `requesting_user` fixture is used.
- Verify `patch_check_token` is applied (it should be automatic via conftest).
- Do not manually patch authentication mechanisms.
