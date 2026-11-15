"""Output sensors are told apart from inputs by one list of fields, wherever access is checked."""

from flexmeasures.auth import loaders


def test_one_list_of_output_fields():
    """Stored flex-configs (E2) and schedule triggers (E9) use the same fields."""
    assert loaders.FLEX_CONFIG_OUTPUT_FIELDS == loaders.OUTPUT_SENSOR_FIELDS
    assert loaders.SCHEDULE_OUTPUT_FIELDS == loaders.OUTPUT_SENSOR_FIELDS
    for field in (
        "aggregate-power",
        "aggregate_power",
        "state-of-charge",
        "state_of_charge",
        "group",
    ):
        assert field in loaders.OUTPUT_SENSOR_FIELDS
