import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.tests.utils import get_test_sensor
from flexmeasures.utils.calculations import integrate_time_series
from flexmeasures.utils.unit_utils import ur


def check_constraints(
    sensor: Sensor,
    schedule: pd.Series,
    soc_at_start: float,
    roundtrip_efficiency: float = 1,
    storage_efficiency: float = 1,
    tolerance: float = 0.00001,
) -> pd.Series:
    soc_schedule = integrate_time_series(
        schedule,
        soc_at_start,
        up_efficiency=roundtrip_efficiency**0.5,
        down_efficiency=roundtrip_efficiency**0.5,
        storage_efficiency=storage_efficiency,
        decimal_precision=6,
    )
    with pd.option_context("display.max_rows", None, "display.max_columns", 3):
        print(soc_schedule)
    capacity = sensor.get_attribute(
        "capacity_in_mw",
        ur.Quantity(sensor.get_attribute("site-power-capacity")).to("MW").magnitude,
    )
    assert min(schedule.values) >= capacity * -1 - tolerance
    assert max(schedule.values) <= capacity + tolerance
    for soc in soc_schedule.values:
        assert soc >= sensor.get_attribute("min_soc_in_mwh")
        assert soc <= sensor.get_attribute("max_soc_in_mwh")
    return soc_schedule


def get_sensors_from_db(
    db, battery_assets, battery_name="Test battery", power_sensor_name="power"
):
    # get the sensors from the database
    epex_da = get_test_sensor(db)
    battery = [
        s for s in battery_assets[battery_name].sensors if s.name == power_sensor_name
    ][0]
    assert battery.get_attribute("market_id") == epex_da.id

    return epex_da, battery
