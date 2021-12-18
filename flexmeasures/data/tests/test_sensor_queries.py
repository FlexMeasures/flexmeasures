from flexmeasures.data.services.resources import find_closest_sensor


def test_closest_sensor(add_nearby_weather_sensors):
    """Check that the closest temperature sensor to our wind sensor returns
    the one that is on the same spot as the wind sensor itself.
    (That's where we set it up in our conftest.)
    And check that the 2nd and 3rd closest are the farther temperature sensors we set up.
    """
    wind_sensor = add_nearby_weather_sensors["wind"]
    generic_asset_type_name = "temperature"
    closest_sensors = find_closest_sensor(
        generic_asset_type_name,
        n=3,
        latitude=wind_sensor.latitude,
        longitude=wind_sensor.longitude,
    )
    assert closest_sensors[0].location == wind_sensor.location
    assert (
        closest_sensors[1]
        == add_nearby_weather_sensors["farther_temperature"].corresponding_sensor
    )
    assert (
        closest_sensors[2]
        == add_nearby_weather_sensors["even_farther_temperature"].corresponding_sensor
    )
    for sensor in closest_sensors:
        assert sensor.generic_asset.generic_asset_type.name == generic_asset_type_name
