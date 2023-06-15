from datetime import datetime, timedelta
import pytest
import pytz
from flexmeasures.data.models.planning.storage import (
    StorageScheduler,
)
from flexmeasures.utils.calculations import integrate_time_series


TOLERANCE = 0.00001


@pytest.mark.parametrize(
    "roundtrip_efficiency",
    [
        0.90,
        0.95,
    ],
)
def test_schedule_multiple_price_sensors(
    create_solar_plants, create_building, flexible_devices, roundtrip_efficiency: float
):
    """
    Using a dictionary of price sensors mapped to different devices to schedule the battery and check it's scheduling results for tomorrow.
    """
    (
        solar1_production_price_sensor,
        solar1_power_sensor,
        solar2_production_price_sensor,
        solar2_power_sensor,
        solar3_production_price_sensor,
        solar3_power_sensor,
    ) = create_solar_plants
    building_consumption_price_sensor, building_power = create_building
    (
        battery_consumption_price_sensor,
        battery_production_price_sensor,
        battery,
        grid_consumption_price_sensor,
        grid_production_price_sensor,
        grid_power,
    ) = flexible_devices
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=60)
    soc_at_start = 545
    soc_min = 0.5
    soc_max = 795
    inflexible_devices = [
        solar1_power_sensor.id,
        building_power.id,
    ]
    consumption_price_sensor_per_device = {
        grid_power.id: grid_consumption_price_sensor.id
    }
    production_price_sensor_per_device = {
        solar1_power_sensor.id: solar1_production_price_sensor.id,
        grid_power.id: grid_production_price_sensor.id,
    }
    scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": soc_at_start,
            "soc-unit": "MWh",
            "soc-min": soc_min,
            "soc-max": soc_max,
            "roundtrip-efficiency": roundtrip_efficiency,
        },
        flex_context={
            "inflexible-device-sensors": inflexible_devices,
            "consumption-price-sensor-per-device": consumption_price_sensor_per_device,
            "production-price-sensor-per-device": production_price_sensor_per_device,
        },
    )
    schedule = scheduler.compute()
    soc_schedule = integrate_time_series(
        schedule,
        soc_at_start,
        up_efficiency=roundtrip_efficiency**0.5,
        down_efficiency=roundtrip_efficiency**0.5,
        decimal_precision=5,
    )
    # Check if constraints were met
    assert (
        min(schedule.values) >= battery.get_attribute("capacity_in_mw") * -1 - TOLERANCE
    )
    assert max(schedule.values) <= battery.get_attribute("capacity_in_mw")
    for soc in soc_schedule.values:
        assert soc >= battery.get_attribute("min_soc_in_mwh")
        assert soc <= battery.get_attribute("max_soc_in_mwh")
