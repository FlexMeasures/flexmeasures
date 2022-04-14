from flexmeasures.data.models.time_series import Sensor


def test_closest_sensor(run_as_cli, add_nearby_weather_sensors):
    """Check that the closest temperature sensor to our wind sensor returns
    the one that is on the same spot as the wind sensor itself.
    (That's where we set it up in our conftest.)
    And check that the 2nd and 3rd closest are the farther temperature sensors we set up.
    """
    wind_sensor = add_nearby_weather_sensors["wind"]
    closest_sensors = Sensor.find_closest(
        generic_asset_type_name=wind_sensor.generic_asset.generic_asset_type.name,
        n=3,
        sensor_name="temperature",
        latitude=wind_sensor.generic_asset.latitude,
        longitude=wind_sensor.generic_asset.longitude,
    )
    assert closest_sensors[0].location == wind_sensor.generic_asset.location
    assert closest_sensors[1] == add_nearby_weather_sensors["farther_temperature"]
    assert closest_sensors[2] == add_nearby_weather_sensors["even_farther_temperature"]
    for sensor in closest_sensors:
        assert (
            sensor.generic_asset.generic_asset_type.name
            == wind_sensor.generic_asset.generic_asset_type.name
        )
