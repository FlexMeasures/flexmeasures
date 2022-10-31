from decimal import Decimal

import pytest

from flexmeasures.data.schemas.assets import LatitudeField, LongitudeField
from flexmeasures.data.schemas.utils import ValidationError


@pytest.mark.parametrize(
    ("input", "exp_deserialization"),
    [
        (0, 0),
        (0.12345678, 0.1234568),  # note the rounding to 7 digits
        (-90, -90),
    ],
)
def test_latitude(input, exp_deserialization):
    """Testing straightforward cases"""
    lf = LatitudeField()
    deser = lf.deserialize(input, None, None)
    assert deser == exp_deserialization
    assert lf.serialize("duration", {"duration": deser}) == round(input, 7)


@pytest.mark.parametrize(
    ("input", "error_msg"),
    [
        (-90.01, "Must be greater than or equal to -90 and less than or equal to 90."),
        # Even though it would have been a valid latitude after rounding to 7 decimal places
        (
            -90.0000001,
            "Must be greater than or equal to -90 and less than or equal to 90.",
        ),
        ("ninety", "Not a valid number."),
    ],
)
def test_latitude_field_invalid(input, error_msg):
    lf = LatitudeField()
    with pytest.raises(ValidationError) as ve:
        lf.deserialize(input, None, None)
    assert error_msg in str(ve)


@pytest.mark.parametrize(
    ("input", "exp_deserialization"),
    [
        (0, 0),
        (0.12345678, 0.1234568),  # note the rounding to 7 digits
        (-180, -180),
    ],
)
def test_longitude(input, exp_deserialization):
    """Testing straightforward cases"""
    lf = LongitudeField()
    deser = lf.deserialize(input, None, None)
    assert deser == exp_deserialization
    assert lf.serialize("duration", {"duration": deser}) == round(input, 7)


@pytest.mark.parametrize(
    ("input", "error_msg"),
    [
        (
            -180.01,
            "Must be greater than or equal to -180 and less than or equal to 180.",
        ),
        # Even though it would have been a valid latitude after rounding to 7 decimal places
        (
            -180.0000001,
            "Must be greater than or equal to -180 and less than or equal to 180.",
        ),
        ("one-hundred-and-eighty", "Not a valid number."),
    ],
)
def test_longitude_field_invalid(input, error_msg):
    lf = LongitudeField()
    with pytest.raises(ValidationError) as ve:
        lf.deserialize(input, None, None)
    assert error_msg in str(ve)
