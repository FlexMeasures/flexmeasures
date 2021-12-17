from flexmeasures.data.services.resources import find_closest_sensor


def test_closest_sensor(add_weather_sensors):
    """Check that the closest temperature sensor to our wind sensor returns
    the one that is on the same spot as the wind sensor itself.
    (That's where we set it up in our conftest.)
    """
    wind_sensor = add_weather_sensors["wind"]
    generic_asset_type_name = "temperature"
    closest_sensor = find_closest_sensor(
        generic_asset_type_name,
        latitude=wind_sensor.latitude,
        longitude=wind_sensor.longitude,
    )
    assert closest_sensor.location == wind_sensor.location
    assert (
        closest_sensor.generic_asset.generic_asset_type.name == generic_asset_type_name
    )
