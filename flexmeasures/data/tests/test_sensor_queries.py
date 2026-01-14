import pytest

from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("n", [1, 3])
def test_closest_sensor(run_as_cli, add_nearby_weather_sensors, n):
    """Check that the closest temperature sensor to our wind sensor returns
    the one that is on the same spot as the wind sensor itself.
    (That's where we set it up in our conftest.)
    And check that the 2nd and 3rd closest are the farther temperature sensors we set up, in the case of 3 sensors.
    """
    wind_sensor = add_nearby_weather_sensors["wind"]
    closest_sensor_or_sensors = Sensor.find_closest(
        generic_asset_type_name=wind_sensor.generic_asset.generic_asset_type.name,
        n=n,
        sensor_name="temperature",
        latitude=wind_sensor.generic_asset.latitude,
        longitude=wind_sensor.generic_asset.longitude,
    )
    if n == 1:
        assert closest_sensor_or_sensors.location == wind_sensor.generic_asset.location
        assert (
            closest_sensor_or_sensors.generic_asset.generic_asset_type.name
            == wind_sensor.generic_asset.generic_asset_type.name
        )
    elif n == 3:
        assert (
            closest_sensor_or_sensors[0].location == wind_sensor.generic_asset.location
        )
        assert (
            closest_sensor_or_sensors[1]
            == add_nearby_weather_sensors["farther_temperature"]
        )
        assert (
            closest_sensor_or_sensors[2]
            == add_nearby_weather_sensors["even_farther_temperature"]
        )
        for sensor in closest_sensor_or_sensors:
            assert (
                sensor.generic_asset.generic_asset_type.name
                == wind_sensor.generic_asset.generic_asset_type.name
            )
