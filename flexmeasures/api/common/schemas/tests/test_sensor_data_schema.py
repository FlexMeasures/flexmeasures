import pytest

from marshmallow import ValidationError

from flexmeasures.api.common.schemas.sensor_data import (
    SingleValueField,
    SensorDataSchema,
)


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
    ],
)
def test_value_field_deserialization(
    deserialization_input,
    exp_deserialization_output,
):
    """Testing straightforward cases"""
    vf = SensorDataSchema.values
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
    ],
)
def test_value_field_invalid(deserialization_input, error_msg):
    sf = SingleValueField()
    with pytest.raises(ValidationError) as ve:
        sf.deserialize(deserialization_input)
    assert error_msg in str(ve)
