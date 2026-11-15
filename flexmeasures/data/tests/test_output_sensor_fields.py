"""Output sensors are told apart from inputs by one list of fields, wherever access is checked."""

import pytest

from flexmeasures.auth import loaders
from flexmeasures.data.services import automations


def test_one_list_of_output_fields():
    """Stored flex-configs (E2), schedule triggers (E9) and scheduling automations (V3) use the same fields."""
    assert loaders.FLEX_CONFIG_OUTPUT_FIELDS == loaders.OUTPUT_SENSOR_FIELDS
    assert loaders.SCHEDULE_OUTPUT_FIELDS == loaders.OUTPUT_SENSOR_FIELDS
    assert set(automations.OUTPUT_SENSOR_FIELDS) == set(loaders.OUTPUT_SENSOR_FIELDS)
    for field in (
        "aggregate-power",
        "aggregate_power",
        "state-of-charge",
        "state_of_charge",
        "group",
    ):
        assert field in loaders.OUTPUT_SENSOR_FIELDS


@pytest.mark.parametrize("field", ["aggregate-power", "aggregate_power"])
def test_scheduling_automations_record_on_the_aggregate_power_sensor(
    db, setup_markets, field
):
    """A scheduling automation's aggregate-power sensor is an output, so its creator needs to be allowed to record on it."""
    sensor = setup_markets["epex_da"]
    output_sensors = automations.collect_schedule_output_sensors(
        {"flex_model": [], "flex_context": {field: {"sensor": sensor.id}}}
    )
    assert sensor in output_sensors
