---
applyTo: "**/*.py"
---
# Error Handling

Catch specific exceptions, not bare `Exception`. Broad catches hide bugs and make debugging difficult.

## What to catch and when

```python
from sqlalchemy.exc import SQLAlchemyError

# ✅ Catch specific, expected failures
try:
    obj = create_or_fetch(...)
except SQLAlchemyError as e:
    db.session.rollback()
    return error_response("Database error", 500)
except ValueError as e:
    return error_response(str(e), 400)
# Let unexpected exceptions (AttributeError, TypeError, etc.) propagate
# — they indicate bugs that should fail loudly
```

## Never do this

```python
# ❌ Too broad: catches programming errors
try:
    result = some_operation()
except Exception as e:
    return error_response("Something went wrong")
```

## Exception categories

| Exception type | When to catch |
|----------------|---------------|
| `SQLAlchemyError` | Database connection, integrity, or query errors |
| `ValueError` | Invalid input that was expected and validated |
| `KeyError` | Missing required data in a known structure |
| `AttributeError` | **Never** — indicates a bug in your code |
| `TypeError` | **Never** — indicates a bug in your code |
| `NameError` | **Never** — indicates a bug in your code |

## Error messages

Good error messages state what went wrong, explain why, and suggest a fix:

```python
raise ValueError(
    f"Invalid sensor ID {sensor_id}. "
    f"Sensor must belong to account {account.name}. "
    f"See https://flexmeasures.readthedocs.io/..."
)
```

## HTTP status codes in API endpoints

- `400 Bad Request` — invalid client input (validation failure)
- `401 Unauthorized` — authentication required
- `403 Forbidden` — authenticated but not permitted
- `404 Not Found` — resource does not exist
- `500 Internal Server Error` — unexpected server-side failure

## get-or-create idempotency

Never rely on `obj.id is None` to detect if an object is newly created (SQLAlchemy may not assign IDs until commit). Return an explicit boolean instead:

```python
def get_or_create_thing(...):
    existing = db.session.query(Thing).filter_by(...).first()
    if existing:
        return existing, False  # (object, was_created)
    new_obj = Thing(...)
    db.session.add(new_obj)
    return new_obj, True

thing, was_created = get_or_create_thing(...)
status_code = 201 if was_created else 200
```
