import pytest

from flexmeasures.data.schemas.sensors import sensor_reference_keys
from flexmeasures.data.services.sensors import _prune_flex_config_sensor_refs


@pytest.mark.parametrize("key", sorted(sensor_reference_keys() - {"sensor"}))
def test_reference_with_any_schema_key_keeps_it_and_loses_its_sensor(key):
    """A reference may carry any key of SensorReferenceSchema (source filters, a default, bounds), which is kept for a new sensor."""
    config = {
        "site-power-capacity": {"sensor": 42, key: "placeholder"},
        "other": "1 MW",
    }
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is True
    assert pruned == {
        "site-power-capacity": {"sensor": None, key: "placeholder"},
        "other": "1 MW",
    }


def test_reference_with_only_a_sensor_is_removed():
    config = {"site-power-capacity": {"sensor": 42}, "other": "1 MW"}
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is True
    assert pruned == {"other": "1 MW"}


@pytest.mark.parametrize(
    "reference",
    [
        {"sensor": 42},
        {"sensor": 42, "default": "1 MW"},
        {"sensor": 42, "lower": "0 kW", "upper": "10 kW"},
        {"sensor": 42, "snap": {"0 kW": ["0 kW", "0.5 kW"]}},
        {"sensor": 42, "source-types": ["user"], "default": "1 MW", "lower": "0 kW"},
    ],
)
def test_reference_in_a_list_is_removed(reference):
    """A list entry without a sensor has nothing to read, so it is removed rather than kept without its sensor."""
    config = {"inflexible-consumption": [reference, {"sensor": 7, "default": "1 MW"}]}
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is True
    assert pruned == {"inflexible-consumption": [{"sensor": 7, "default": "1 MW"}]}


def test_reference_to_another_sensor_is_kept():
    config = {"site-power-capacity": {"sensor": 7, "default": "1 MW"}}
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is False
    assert pruned == config


def test_dict_with_an_unknown_key_is_not_a_reference():
    """A dict with a key that no sensor reference has is left alone."""
    config = {"something": {"sensor": 42, "not-a-reference-key": 1}}
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is False
    assert pruned == config
