from datetime import timedelta
import pytest

from marshmallow import ValidationError

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    PostSensorDataSchema,
    GetSensorDataSchema,
)
from flexmeasures.data.schemas.reporting import BeliefsSearchConfigSchema


@pytest.mark.parametrize(
    "deserialization_input, exp_deserialization_output",
    [
        (
            "PT1H",
            timedelta(hours=1),
        ),
        (
            "PT15M",
            timedelta(minutes=15),
        ),
    ],
)
def test_resolution_field_deserialization(
    deserialization_input,
    exp_deserialization_output,
):
    """Check parsing the resolution field of the GetSensorDataSchema schema.

    These particular ISO durations are expected to be parsed as python timedeltas.
    """
    # todo: extend test cases with some nominal durations when timely-beliefs supports these
    #       see https://github.com/SeitaBV/timely-beliefs/issues/13
    vf = GetSensorDataSchema._declared_fields["resolution"]
    deser = vf.deserialize(deserialization_input)
    assert deser == exp_deserialization_output


@pytest.mark.parametrize(
    "deserialization_input, exp_deserialization_output",
    [
        (
            1,
            [1],
        ),
        (
            2.7,
            [2.7],
        ),
        (
            [1],
            [1],
        ),
        (
            [2.7],
            [2.7],
        ),
        (
            [1, None, 3],  # sending a None/null value as part of a list is allowed
            [1, None, 3],
        ),
        (
            [None],  # sending a None/null value as part of a list is allowed
            [None],
        ),
    ],
)
def test_value_field_deserialization(
    deserialization_input,
    exp_deserialization_output,
):
    """Testing straightforward cases"""
    vf = PostSensorDataSchema._declared_fields["values"]
    deser = vf.deserialize(deserialization_input)
    assert deser == exp_deserialization_output


@pytest.mark.parametrize(
    "serialization_input, exp_serialization_output",
    [
        (
            1,
            [1],
        ),
        (
            2.7,
            [2.7],
        ),
    ],
)
def test_value_field_serialization(
    serialization_input,
    exp_serialization_output,
):
    """Testing straightforward cases"""
    vf = SingleValueField()
    ser = vf.serialize("values", {"values": serialization_input})
    assert ser == exp_serialization_output


@pytest.mark.parametrize(
    "deserialization_input, error_msg",
    [
        (
            ["three", 4],
            "Not a valid number",
        ),
        (
            "3, 4",
            "Not a valid number",
        ),
        (
            None,
            "may not be null",  # sending a single None/null value is not allowed
        ),
    ],
)
def test_value_field_invalid(deserialization_input, error_msg):
    sf = SingleValueField()
    with pytest.raises(ValidationError) as ve:
        sf.deserialize(deserialization_input)
    assert error_msg in str(ve)


def test_get_status(add_market_prices, capacity_sensors):
    market_sensor = add_market_prices["epex_da"]
    market_staleness_search = BeliefsSearchConfigSchema().load(
        {
            "sensor": market_sensor.id,
            "horizons_at_most": "PT0H",
            "horizons_at_least": "PT0H",
        }
    )
    # event_starts_after = AwareDateTimeField()
    # event_ends_before = AwareDateTimeField()

    # belief_time = AwareDateTimeField()

    # horizons_at_least = DurationField()
    # horizons_at_most = DurationField()

    # source = DataSourceIdField()

    # source_types = fields.List(fields.Str())
    # exclude_source_types = fields.List(fields.Str())
    # most_recent_beliefs_only = fields.Boolean()
    # most_recent_events_only = fields.Boolean()

    # one_deterministic_belief_per_event = fields.Boolean()
    # one_deterministic_belief_per_event_per_source = fields.Boolean()
    # resolution = DurationField()
    # sum_multiple = fields.Boolean()

    market_beliefs = GetSensorDataSchema.get_staleness(
        staleness_search=market_staleness_search
    )
    production_sensor = capacity_sensors["production"]
    production_staleness_search = BeliefsSearchConfigSchema().load(
        {
            "sensor": production_sensor.id,
        }
    )
    production_beliefs = GetSensorDataSchema.get_staleness(
        staleness_search=production_staleness_search
    )

    assert len(market_beliefs.event_starts) == 4
    assert len(production_beliefs.event_starts) == 4
    assert 1 == 2
