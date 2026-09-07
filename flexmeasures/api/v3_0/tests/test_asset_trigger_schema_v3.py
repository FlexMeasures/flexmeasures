"""Tests for AssetTriggerSchemaV3, the v3_0-only wrapper that adds legacy
field-name backward compatibility on top of the shared, canonical
AssetTriggerSchema (see flexmeasures/api/v3_0/assets.py for why this split
exists: sunsetting v3_0 should be able to delete this compatibility layer in
one place, without touching the domain schema also used by the CLI).
"""

from marshmallow.validate import ValidationError
import pytest
from werkzeug.datastructures import MultiDict

from flexmeasures.api.v3_0.assets import AssetTriggerSchemaV3


def test_asset_trigger_schema_v3_accepts_legacy_force_new_job_creation_field():
    """Regression test for a gap that made flexmeasures-client#218 necessary: the
    sensor-level scheduling trigger schema already accepted both
    `force_new_job_creation` (legacy) and `force-new-job-creation` (canonical),
    but the asset-level trigger schema only accepted the canonical spelling and
    rejected the legacy one (as an unknown field, yielding a 422).
    """
    schema = AssetTriggerSchemaV3()
    normalized = schema._apply_legacy_field_aliases({"force_new_job_creation": True})
    assert normalized == {"force-new-job-creation": True}


def test_asset_trigger_schema_v3_load_accepts_legacy_force_new_job_creation_field(
    db, app
):
    """Same regression as above, but exercised through the real `schema.load(...)`
    deserialization path (not by calling the `@pre_load` helper directly), so
    this fails if the hook ever stops being registered/applied by Marshmallow
    (e.g. decorator removed, or an MRO change means the hook is no longer
    picked up).

    Uses a nonexistent asset id, so `load()` is expected to still raise -- but
    only about the asset, never about `force_new_job_creation` being an
    unrecognized field. If the legacy alias stopped working, Marshmallow's
    default `unknown` handling would additionally report `force_new_job_creation`
    as an unknown field.
    """
    schema = AssetTriggerSchemaV3()
    with pytest.raises(ValidationError) as e_info:
        schema.load(
            {
                "id": 2**31 - 1,  # some asset id that doesn't exist
                "start": "2026-01-15T10:00:00+01:00",
                "force_new_job_creation": True,  # legacy spelling
            }
        )
    messages = e_info.value.messages
    assert "force_new_job_creation" not in messages, (
        "the legacy field name should have been aliased to "
        "`force-new-job-creation` before validation, not rejected as an "
        f"unknown field; got: {messages}"
    )
    assert (
        "id" in messages
    ), f"expected the (nonexistent) asset id to fail; got: {messages}"


def test_asset_trigger_schema_v3_preserves_multidict_when_aliasing():
    """Regression test: aliasing a legacy field must not destroy MultiDict
    semantics (e.g. `getlist`) for other, untouched keys -- this is relied on
    by `AssetTriggerSchema.normalize_flex_context_format` to detect a
    multi-commodity `flex-context` list sent as repeated keys.
    """
    schema = AssetTriggerSchemaV3()
    data = MultiDict(
        [
            ("start", "2026-01-15T10:00+01:00"),
            ("force_new_job_creation", True),
            ("flex-context", "electricity"),
            ("flex-context", "heat"),
        ]
    )
    normalized = schema._apply_legacy_field_aliases(data)
    assert normalized.getlist("flex-context") == ["electricity", "heat"]
    assert normalized["force-new-job-creation"] is True
    assert "force_new_job_creation" not in normalized
