import pytest
from marshmallow import ValidationError

from flexmeasures import Sensor
from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema


def test_single_sensor_id():
    schema = SensorsToShowSchema()
    input_value = [42]
    expected_output = [{"title": None, "plots": [{"sensor": 42}]}]
    assert schema.deserialize(input_value) == expected_output


def test_list_of_sensor_ids():
    schema = SensorsToShowSchema()
    input_value = [42, 43]
    expected_output = [
        {"title": None, "plots": [{"sensor": 42}]},
        {"title": None, "plots": [{"sensor": 43}]},
    ]
    assert schema.deserialize(input_value) == expected_output


def test_dict_with_title_and_single_sensor():
    schema = SensorsToShowSchema()
    input_value_one = [{"title": "Temperature", "sensor": 42}]
    input_value_two = [{"title": "Temperature", "plots": [{"sensor": 42}]}]
    expected_output = [{"title": "Temperature", "plots": [{"sensor": 42}]}]
    assert schema.deserialize(input_value_one) == expected_output
    assert schema.deserialize(input_value_two) == expected_output


def test_dict_with_title_and_multiple_sensors():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Pressure", "plots": [{"sensors": [42, 43]}]}]
    expected_output = [{"title": "Pressure", "plots": [{"sensors": [42, 43]}]}]
    assert schema.deserialize(input_value) == expected_output


def test_dict_with_asset_and_no_title_plot(setup_test_data):
    asset_id = setup_test_data["wind-asset-1"].id
    schema = SensorsToShowSchema()
    input_value = [{"plots": [{"asset": asset_id, "flex-model": "soc-min"}]}]
    expected_output = [
        {"title": None, "plots": [{"asset": asset_id, "flex-model": "soc-min"}]}
    ]
    assert schema.deserialize(input_value) == expected_output


def _get_sensor_by_name(sensors: list[Sensor], name: str) -> Sensor:
    for sensor in sensors:
        if sensor.name == name:
            return sensor
    raise ValueError(f"Sensor {name} not found")


def test_flatten_with_multiple_flex_config_fields(setup_test_data):
    asset = setup_test_data["wind-asset-1"]
    schema = SensorsToShowSchema()
    input_value = [
        {
            "plots": [
                {
                    "asset": asset.id,
                    "flex-model": ["consumption-capacity", "production-capacity"],
                    "flex-context": "site-consumption-capacity",
                }
            ]
        }
    ]
    expected_output = [
        _get_sensor_by_name(asset.sensors, name).id
        for name in (
            "site-consumption-capacity",
            "consumption-capacity",
            "production-capacity",
        )
    ]
    assert schema.flatten(input_value) == expected_output


def test_invalid_sensor_string_input():
    schema = SensorsToShowSchema()
    with pytest.raises(
        ValidationError,
        match="Invalid item type in 'sensors_to_show'. Expected int, list, or dict.",
    ):
        schema.deserialize(["invalid_string"])


def test_invalid_sensor_in_list():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Test", "sensors": [42, "invalid"]}]
    with pytest.raises(
        ValidationError, match="'sensors' value must be a list of integers."
    ):
        schema.deserialize(input_value)


def test_invalid_sensor_dict_without_sensors_key():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Test", "something_else": 42}]
    with pytest.raises(
        ValidationError,
        match="Dictionary must contain either 'sensor', 'sensors' or 'plots' key.",
    ):
        schema.deserialize(input_value)


def test_mixed_valid_inputs():
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Test", "sensors": [1, 2]},
        {"title": None, "sensors": [3, 4]},
        5,
    ]
    expected_output = [
        {"title": "Test", "plots": [{"sensors": [1, 2]}]},
        {"title": None, "plots": [{"sensors": [3, 4]}]},
        {"title": None, "plots": [{"sensor": 5}]},
    ]
    assert schema.deserialize(input_value) == expected_output


def test_string_json_input():
    schema = SensorsToShowSchema()
    input_value = (
        '[{"title": "Test", "sensors": [1, 2]}, {"title": "Test2", "sensors": [3]}]'
    )
    expected_output = [
        {"title": "Test", "plots": [{"sensors": [1, 2]}]},
        {"title": "Test2", "plots": [{"sensors": [3]}]},
    ]
    assert schema.deserialize(input_value) == expected_output


def test_dict_with_sensor_as_list():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Temperature", "sensor": [42]}]
    with pytest.raises(ValidationError, match="'sensor' value must be an integer."):
        schema.deserialize(input_value)


def test_dict_with_sensors_as_int():
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Temperature", "sensors": 42}
    ]  # 'sensors' should be a list, not an int
    with pytest.raises(
        ValidationError, match="'sensors' value must be a list of integers."
    ):
        schema.deserialize(input_value)
