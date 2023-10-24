import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.calculations import integrate_time_series


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
    assert (
        min(schedule.values) >= sensor.get_attribute("capacity_in_mw") * -1 - tolerance
    )
    assert max(schedule.values) <= sensor.get_attribute("capacity_in_mw") + tolerance
    for soc in soc_schedule.values:
        assert soc >= sensor.get_attribute("min_soc_in_mwh")
        assert soc <= sensor.get_attribute("max_soc_in_mwh")
    return soc_schedule
