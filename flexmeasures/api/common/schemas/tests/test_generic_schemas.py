import pytest
from marshmallow import ValidationError

from flexmeasures.api.common.schemas.generic_schemas import (
    EventWindowSchema,
    BeliefTimeFilterSchema,
)


def test_event_window_schema_start_and_end():
    data = EventWindowSchema().load(
        {"start": "2025-05-01T00:00:00+02:00", "end": "2025-05-02T00:00:00+02:00"}
    )
    assert "event_starts_after" in data
    assert "event_ends_before" in data


def test_event_window_schema_derives_end_from_start_and_duration():
    data = EventWindowSchema().load(
        {"start": "2025-05-01T00:00:00+02:00", "duration": "P1D"}
    )
    assert "duration" not in data
    assert (data["event_ends_before"] - data["event_starts_after"]).days == 1


def test_event_window_schema_derives_start_from_end_and_duration():
    data = EventWindowSchema().load(
        {"end": "2025-05-02T00:00:00+02:00", "duration": "P1D"}
    )
    assert (data["event_ends_before"] - data["event_starts_after"]).days == 1


def test_event_window_schema_derives_bound_from_nominal_duration():
    """Regression test: a nominal duration (e.g. "P1M", a calendar month) deserializes
    to an isodate.Duration, not a timedelta, and can't be added to/subtracted from a
    datetime directly -- it must first be grounded to a concrete timedelta."""
    data = EventWindowSchema().load(
        {"start": "2025-01-31T00:00:00+01:00", "duration": "P1M"}
    )
    assert data["event_ends_before"] == data["event_starts_after"].replace(
        month=2, day=28
    )

    data = EventWindowSchema().load(
        {"end": "2025-03-31T00:00:00+02:00", "duration": "P1M"}
    )
    assert data["event_starts_after"] == data["event_ends_before"].replace(
        month=2, day=28
    )


def test_event_window_schema_duration_alone_is_rejected():
    with pytest.raises(ValidationError) as e_info:
        EventWindowSchema().load({"duration": "P1D"})
    assert "duration" in e_info.value.messages


def test_event_window_schema_legacy_field_names_still_work():
    data = EventWindowSchema().load(
        {
            "event_starts_after": "2025-05-01T00:00:00+02:00",
            "event_ends_before": "2025-05-02T00:00:00+02:00",
        }
    )
    assert "event_starts_after" in data
    assert "event_ends_before" in data


def test_belief_time_filter_schema_hyphenated_and_legacy_names():
    canonical = BeliefTimeFilterSchema().load(
        {
            "prior": "2025-05-01T00:00:00+02:00",
            "beliefs-after": "2025-04-01T00:00:00+02:00",
        }
    )
    legacy = BeliefTimeFilterSchema().load(
        {
            "beliefs_before": "2025-05-01T00:00:00+02:00",
            "beliefs_after": "2025-04-01T00:00:00+02:00",
        }
    )
    assert canonical == legacy
