import pytest
from marshmallow import ValidationError

from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema


def test_single_sensor_id():
    schema = SensorsToShowSchema()
    input_value = [42]
    expected_output = [{"title": None, "sensors": [42]}]
    assert schema.deserialize(input_value) == expected_output


def test_list_of_sensor_ids():
    schema = SensorsToShowSchema()
    input_value = [42, 43]
    expected_output = [
        {"title": None, "sensors": [42]},
        {"title": None, "sensors": [43]},
    ]
    assert schema.deserialize(input_value) == expected_output


def test_dict_with_title_and_single_sensor():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Temperature", "sensor": 42}]
    expected_output = [{"title": "Temperature", "sensors": [42]}]
    assert schema.deserialize(input_value) == expected_output


def test_dict_with_title_and_multiple_sensors():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Pressure", "sensors": [42, 43]}]
    expected_output = [{"title": "Pressure", "sensors": [42, 43]}]
    assert schema.deserialize(input_value) == expected_output


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
        match="Dictionary must contain either 'sensor' or 'sensors' key.",
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
        {"title": "Test", "sensors": [1, 2]},
        {"title": None, "sensors": [3, 4]},
        {"title": None, "sensors": [5]},
    ]
    assert schema.deserialize(input_value) == expected_output


def test_string_json_input():
    schema = SensorsToShowSchema()
    input_value = (
        '[{"title": "Test", "sensors": [1, 2]}, {"title": "Test2", "sensors": [3]}]'
    )
    expected_output = [
        {"title": "Test", "sensors": [1, 2]},
        {"title": "Test2", "sensors": [3]},
    ]
    assert schema.deserialize(input_value) == expected_output


# New test cases for misspelled or missing title and mixed sensor/sensors formats


def test_dict_missing_title_key():
    schema = SensorsToShowSchema()
    input_value = [{"sensor": 42}]
    with pytest.raises(ValidationError, match="Dictionary must contain a 'title' key."):
        schema.deserialize(input_value)


def test_dict_misspelled_title_key():
    schema = SensorsToShowSchema()
    input_value = [{"titel": "Temperature", "sensor": 42}]  # Misspelled 'title'
    with pytest.raises(ValidationError, match="Dictionary must contain a 'title' key."):
        schema.deserialize(input_value)


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
