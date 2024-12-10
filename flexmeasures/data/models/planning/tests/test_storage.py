from datetime import datetime, timedelta
import pytest
import pytz

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.tests.utils import check_constraints, get_sensors_from_db


@pytest.mark.parametrize("use_inflexible_device", [
    False,
    # True,
])
@pytest.mark.parametrize("battery_name", [
    "Test battery",
    # "Test small battery",
])
def test_battery_solver_multi_commitment(
    add_battery_assets,
    add_inflexible_device_forecasts,
    use_inflexible_device,
    battery_name,
    db,
):
    epex_da, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name=battery_name
    )
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = battery.get_attribute("soc_in_mwh")
    print(soc_at_start)
    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={"soc-at-start": soc_at_start},
        flex_context={
            "inflexible-device-sensors": (
                [s.id for s in add_inflexible_device_forecasts.keys()]
                if use_inflexible_device
                else []
            ),
            "consumption-price-sensor": epex_da.id,
            "production-price-sensor": epex_da.id,
            "site-power-capacity": "2 MW",  # should be big enough to avoid any infeasibilities
            "site-consumption-capacity": "100 kW",  # we'll breach this
            "site-consumption-breach-price": "1000 EUR/kW",
            "site-production-breach-price": "1000 EUR/kW",
            "site-peak-consumption": "50 kW",
            "site-peak-production": "50 kW",
            "site-peak-consumption-price": "260 EUR/MW",
            "site-peak-production-price": "260 EUR/MW",
        },
    )
    schedule = scheduler.compute()

    # Check if constraints were met
    check_constraints(battery, schedule, soc_at_start)
