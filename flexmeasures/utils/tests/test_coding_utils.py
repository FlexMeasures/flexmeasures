import pytest

from flexmeasures import Asset, AssetType, Sensor
from flexmeasures.utils.coding_utils import deprecated


def other_function():
    return 1


def test_deprecated_decorator(caplog, app):

    # defining a function that is deprecated
    @deprecated(other_function, "v14")
    def deprecated_function():
        return other_function()

    caplog.clear()

    value = deprecated_function()  # calling a deprecated function
    print(caplog.records)
    assert len(caplog.records) == 1  # only 1 warning being printed

    assert "flexmeasures.utils.tests.test_coding_utils:other_function" in str(
        caplog.records[0].message
    )  # checking that the message is correct

    assert "v14" in str(
        caplog.records[0].message
    )  # checking that the message is correct

    assert (
        value == 1
    )  # check that the decorator is returning the value of `other_function`


def test_unhashable_entities_as_dict_keys(db):
    """Check for a useful error message when using un-flushed sensors as dict keys."""
    asset_type = AssetType(name="foo")
    asset = Asset(name="bar", generic_asset_type=asset_type)
    sensors = [Sensor(name=name, generic_asset=asset) for name in ["A", "B"]]
    for sensor in sensors:
        db.session.add(sensor)
    with pytest.raises(TypeError) as exc_info:
        sensor_dict = {s: s.name for s in sensors}  # noqa: F841
    assert (
        "Consider calling `db.session.flush()` before using Sensor objects in sets or as dictionary keys."
        in str(exc_info)
    )
