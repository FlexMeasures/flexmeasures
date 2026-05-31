---
applyTo: "flexmeasures/data/schemas/**/*.py"
---
# Marshmallow Schema Conventions

## `data_key` defines the actual dictionary key

When a Marshmallow field has a `data_key` attribute, the serialized/deserialized dictionary uses the `data_key` value, **not** the Python attribute name. All code that accesses, cleans, stores, or compares such dictionaries must use the `data_key` values.

```python
class ForecasterParametersSchema(Schema):
    as_job = fields.Boolean(data_key="as-job")      # dict key: "as-job"
    sensor_to_save = SensorIdField(data_key="sensor-to-save")  # dict key: "sensor-to-save"
```

```python
# ✅ Correct: use data_key format
params.pop("as-job", None)
value = params.get("sensor-to-save")

# ❌ Wrong: Python attribute name — key does not exist in the dict
params.pop("as_job", None)
value = params.get("sensor_to_save")
```

## Audit all code paths that touch schema output

When a schema changes format (e.g., snake_case → kebab-case migration), update **every** code path that accesses those dictionaries:

1. Parameter cleaning (`.pop()`, `del`, `fields_to_remove`)
2. Parameter access (`.get()`, `[]`)
3. DataSource attributes storage
4. RQ job metadata (`job.meta`)
5. Schema parity across related schemas (see below)

## Schema parity: `Input` and `BeliefsSearchConfigSchema`

Two separate Marshmallow schemas expose `Sensor.search_beliefs` parameters:

- `flexmeasures/data/schemas/io.py` → `Input` (used by reporters and forecasters)
- `flexmeasures/data/schemas/reporting/__init__.py` → `BeliefsSearchConfigSchema` (used by sensor status config)

When adding a parameter to `Sensor.search_beliefs`, add it to **both** schemas. Omitting one creates a silent gap where documented features fail at schema validation.

## API endpoint schemas

Use one schema that separates load vs. dump behaviour with `dump_only` and `load_only`:

```python
class AnnotationSchema(Schema):
    id = fields.Int(
        dump_only=True,  # server-generated; excluded from request validation
        metadata=dict(description="The annotation's ID.", example=19),
    )
    content = fields.Str(
        required=True,
        validate=Length(max=1024),
        metadata={"description": "Text content (max 1024 chars).", "examples": ["Maintenance"]},
    )
    source_id = fields.Int(
        data_key="source",  # serialized as "source" in JSON
        dump_only=True,
        metadata=dict(description="Data source ID.", example=21),
    )
```

- Always include `metadata` with `description` and at least one `example`.
- Use single-word `data_key` values where possible (prefer `"source"` over `"source_id"`).
- `dump_only=True` fields are excluded from request body validation and appear only in responses.
