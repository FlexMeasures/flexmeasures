import pytest

from flexmeasures.data.schemas.sensors import SensorReferenceSchema
from flexmeasures.data.services.sensors import _prune_flex_config_sensor_refs


def _schema_keys() -> list[str]:
    return sorted(f.data_key or n for n, f in SensorReferenceSchema().fields.items())


@pytest.mark.parametrize("key", [k for k in _schema_keys() if k != "sensor"])
def test_reference_with_any_schema_key_is_pruned(key):
    """A reference may carry any key of SensorReferenceSchema (source filters, a default, bounds)."""
    config = {
        "site-power-capacity": {"sensor": 42, key: "placeholder"},
        "other": "1 MW",
    }
    pruned, changed = _prune_flex_config_sensor_refs(config, sensor_id=42)
    assert changed is True
    assert pruned == {"other": "1 MW"}


@pytest.mark.parametrize(
    "reference",
    [
        {"sensor": 42},
        {"sensor": 42, "default": "1 MW"},
        {"sensor": 42, "lower": "0 kW", "upper": "10 kW"},
        {"sensor": 42, "snap": {"0 kW": "0 kW"}},
        {"sensor": 42, "source-types": ["user"], "default": "1 MW", "lower": "0 kW"},
    ],
)
def test_reference_in_a_list_is_pruned(reference):
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
