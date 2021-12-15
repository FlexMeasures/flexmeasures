from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


def test_closest_sensor(add_weather_sensors):
    """Check that the closest temperature sensor to our wind sensor returns
    the one that is on the same spot as the wind sensor itself.
    (That's where we set it up in our conftest.)
    """
    wind_sensor = add_weather_sensors["wind"]
    generic_asset_type_name = "temperature"
    closest_sensor = get_closest_sensor(
        generic_asset_type_name, wind_sensor.latitude, wind_sensor.longitude
    )
    assert closest_sensor.location == wind_sensor.location
    assert (
        closest_sensor.generic_asset.generic_asset_type.name == generic_asset_type_name
    )


def get_closest_sensor(
    generic_asset_type_name: str, latitude: float, longitude: float
) -> Sensor:
    closest_sensor = (
        Sensor.query.join(GenericAsset, GenericAssetType)
        .filter(
            Sensor.generic_asset_id == GenericAsset.id,
            GenericAsset.generic_asset_type_id == GenericAssetType.id,
            GenericAssetType.name == generic_asset_type_name,
        )
        .order_by(GenericAsset.great_circle_distance(lat=latitude, lng=longitude).asc())
        .first()
    )
    return closest_sensor
