import pytest

from marshmallow.exceptions import ValidationError

from flexmeasures.data.schemas.locations import LatitudeField, LongitudeField


@pytest.mark.parametrize(
    ("input", "exp_deserialization"),
    [
        (0, 0),
        (0.1234567, 0.1234567),
        (-90, -90),
        (90, 90),
    ],
)
def test_latitude(input, exp_deserialization):
    """Testing straightforward cases"""
    lf = LatitudeField()
    deser = lf.deserialize(input, None, None)
    assert deser == exp_deserialization
    assert lf.serialize("duration", {"duration": deser}) == round(input, 7)


@pytest.mark.parametrize(
    ("input", "error_messages"),
    [
        ("ninety", ["Not a valid number."]),
        (90.01, ["Latitude 90.01 exceeds the maximum latitude of 90 degrees."]),
        (0.12345678, ["Latitudes and longitudes are limited to 7 decimal places."]),
        (
            -90.00000001,
            [
                "Latitude -90.00000001 exceeds the minimum latitude of -90 degrees.",
                "Latitudes and longitudes are limited to 7 decimal places.",
            ],
        ),
    ],
)
def test_latitude_field_invalid(input, error_messages):
    lf = LatitudeField()
    with pytest.raises(ValidationError) as ve:
        lf.deserialize(input, None, None)
    assert error_messages == ve.value.messages


@pytest.mark.parametrize(
    ("input", "exp_deserialization"),
    [
        (0, 0),
        (0.1234567, 0.1234567),
        (-180, -180),
        (180, 180),
    ],
)
def test_longitude(input, exp_deserialization):
    """Testing straightforward cases"""
    lf = LongitudeField()
    deser = lf.deserialize(input, None, None)
    assert deser == exp_deserialization
    assert lf.serialize("duration", {"duration": deser}) == round(input, 7)


@pytest.mark.parametrize(
    ("input", "error_messages"),
    [
        ("one-hundred-and-eighty", ["Not a valid number."]),
        (
            -180.01,
            ["Longitude -180.01 exceeds the minimum longitude of -180 degrees."],
        ),
        (
            -180.00000001,
            [
                "Longitude -180.00000001 exceeds the minimum longitude of -180 degrees.",
                "Latitudes and longitudes are limited to 7 decimal places.",
            ],
        ),
    ],
)
def test_longitude_field_invalid(input, error_messages):
    lf = LongitudeField()
    with pytest.raises(ValidationError) as ve:
        lf.deserialize(input, None, None)
    assert error_messages == ve.value.messages
