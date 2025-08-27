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
    asset_type = AssetType(name="foo")
    asset = Asset(name="bar", generic_asset_type=asset_type)
    sensor_a = Sensor(name="A", unit="m", event_resolution="PT15M", generic_asset=asset)
    sensor_b = Sensor(name="B", unit="m", event_resolution="PT15M", generic_asset=asset)
    db.session.add(sensor_a)
    db.session.add(sensor_b)
    sensors = [sensor_a, sensor_b]
    with pytest.raises(TypeError) as exc_info:
        sensor_dict = {s: s.name for s in sensors}  # noqa: F841
    assert (
        "Consider calling `db.session.flush()` before using Sensor objects in sets or as dictionary keys."
        in str(exc_info)
    )
