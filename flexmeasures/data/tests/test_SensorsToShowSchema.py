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
                    # "flex-model": ["consumption-capacity", "production-capacity"], # Future expansion: allow multiple flex-models in one plot
                    "flex-context": "site-consumption-capacity",
                }
            ]
        }
    ]
    expected_output = [
        _get_sensor_by_name(asset.sensors, name).id
        for name in (
            "site-consumption-capacity",
            # "consumption-capacity",
            # "production-capacity",
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


@pytest.mark.parametrize(
    "y_axis_input, y_axis_output",
    [
        ("data", "data"),
        ([10, 20], [10, 20]),
        ([10.5, 20.5], [10.5, 20.5]),
        ({"min": 10, "max": 20}, {"min": 10, "max": 20}),
    ],
)
def test_y_axis_survives_deserialize_plots_shorthand(y_axis_input, y_axis_output):
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Prices", "y-axis": y_axis_input, "plots": [{"sensors": [3, 4]}]}
    ]
    expected_output = [
        {"title": "Prices", "y-axis": y_axis_output, "plots": [{"sensors": [3, 4]}]}
    ]
    assert schema.deserialize(input_value) == expected_output


def test_y_axis_survives_deserialize_sensor_shorthand():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Prices", "y-axis": "data", "sensor": 42}]
    expected_output = [{"title": "Prices", "y-axis": "data", "plots": [{"sensor": 42}]}]
    assert schema.deserialize(input_value) == expected_output


def test_y_axis_survives_deserialize_sensors_shorthand():
    schema = SensorsToShowSchema()
    input_value = [{"title": "Prices", "y-axis": [10, 20], "sensors": [3, 4]}]
    expected_output = [
        {"title": "Prices", "y-axis": [10, 20], "plots": [{"sensors": [3, 4]}]}
    ]
    assert schema.deserialize(input_value) == expected_output


def test_y_axis_zero_is_not_stored():
    """The explicit string 'zero' is accepted but normalized away (it's the default)."""
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Prices", "y-axis": "zero", "plots": [{"sensors": [3, 4]}]}
    ]
    expected_output = [{"title": "Prices", "plots": [{"sensors": [3, 4]}]}]
    assert schema.deserialize(input_value) == expected_output


@pytest.mark.parametrize(
    "invalid_y_axis",
    [
        "yes",
        42,
        [1],
        [1, 2, 3],
        [True, 2],
        [1, True],
        ["a", "b"],
        {"min": 1},
        {"min": 1, "max": 2, "extra": 3},
        {"min": True, "max": 2},
        {"min": "a", "max": "b"},
    ],
)
def test_y_axis_invalid_value_raises(invalid_y_axis):
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Prices", "y-axis": invalid_y_axis, "plots": [{"sensors": [3, 4]}]}
    ]
    with pytest.raises(
        ValidationError,
        match="'y-axis' must be 'zero', 'data', a \\[min, max\\] list of two numbers, or a \\{'min': min, 'max': max\\} dict.",
    ):
        schema.deserialize(input_value)


@pytest.mark.parametrize(
    "y_axis_input",
    [
        [20, 10],
        {"min": 20, "max": 10},
    ],
)
def test_y_axis_min_greater_than_max_raises(y_axis_input):
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Prices", "y-axis": y_axis_input, "plots": [{"sensors": [3, 4]}]}
    ]
    with pytest.raises(
        ValidationError,
        match="'y-axis' domain minimum cannot exceed its maximum.",
    ):
        schema.deserialize(input_value)


def test_y_axis_floor_min_equal_max_is_allowed():
    """A degenerate floor domain is a valid way to always keep one specific value in view."""
    schema = SensorsToShowSchema()
    input_value = [
        {"title": "Prices", "y-axis": [10, 10], "plots": [{"sensors": [3, 4]}]}
    ]
    expected_output = [
        {"title": "Prices", "y-axis": [10, 10], "plots": [{"sensors": [3, 4]}]}
    ]
    assert schema.deserialize(input_value) == expected_output


def test_y_axis_strict_min_equal_max_raises():
    """Unlike the floor domain, a strict domain hard-bounds the axis, so a degenerate
    range would clamp all data to a single pixel - not useful."""
    schema = SensorsToShowSchema()
    input_value = [
        {
            "title": "Prices",
            "y-axis": {"min": 10, "max": 10},
            "plots": [{"sensors": [3, 4]}],
        }
    ]
    with pytest.raises(
        ValidationError,
        match="'y-axis' strict domain minimum and maximum cannot be equal.",
    ):
        schema.deserialize(input_value)


def test_flatten_ignores_y_axis():
    schema = SensorsToShowSchema()
    input_value = [{"y-axis": "data", "plots": [{"sensors": [1, 2]}]}]
    assert schema.flatten(input_value) == [1, 2]
