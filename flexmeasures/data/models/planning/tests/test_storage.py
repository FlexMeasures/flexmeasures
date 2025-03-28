from datetime import datetime, timedelta

import pytz

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import initialize_index
from flexmeasures.data.models.planning.tests.utils import (
    check_constraints,
    get_sensors_from_db,
)


def test_battery_solver_multi_commitment(add_battery_assets, db):
    _, battery = get_sensors_from_db(
        db, add_battery_assets, battery_name="Test battery"
    )
    tz = pytz.timezone("Europe/Amsterdam")
    start = tz.localize(datetime(2015, 1, 1))
    end = tz.localize(datetime(2015, 1, 2))
    resolution = timedelta(minutes=15)
    soc_at_start = 0.4
    index = initialize_index(start=start, end=end, resolution=resolution)
    production_prices = pd.Series(90, index=index)
    consumption_prices = pd.Series(100, index=index)
    scheduler: Scheduler = StorageScheduler(
        battery,
        start,
        end,
        resolution,
        flex_model={
            "soc-at-start": f"{soc_at_start} MWh",
            "soc-min": "0 MWh",
            "soc-max": "1 MWh",
            "power-capacity": "1 MW",
            "soc-minima": [
                {
                    "datetime": "2015-01-02T00:00:00+01:00",
                    "value": "1 MWh",
                }
            ],
            "prefer-charging-sooner": False,
        },
        flex_context={
            "consumption-price": [
                {
                    "start": i.isoformat(),
                    "duration": "PT1H",
                    "value": f"{consumption_prices[i]} EUR/MWh",
                }
                for i in consumption_prices.index
            ],
            "production-price": [
                {
                    "start": i.isoformat(),
                    "duration": "PT1H",
                    "value": f"{production_prices[i]} EUR/MWh",
                }
                for i in production_prices.index
            ],
            "site-power-capacity": "2 MW",  # should be big enough to avoid any infeasibilities
            "site-consumption-capacity": "1 kW",  # we'll need to breach this to reach the target
            "site-consumption-breach-price": "1000 EUR/kW",
            "site-production-breach-price": "1000 EUR/kW",
            "site-peak-consumption": "20 kW",
            "site-peak-production": "20 kW",
            "site-peak-consumption-price": "260 EUR/MW",
            # The following is a constant price, but this checks currency conversion in case a later price field is
            # set to a time series specs (i.e. a list of dicts, where each dict represents a time slot)
            "site-peak-production-price": [
                {
                    "start": i.isoformat(),
                    "duration": "PT1H",
                    "value": "260 EUR/MW",
                }
                for i in production_prices.index
            ],
            "soc-minima-breach-price": "100 EUR/kWh/min",  # high breach price (to mimic a hard constraint)
        },
        return_multiple=True,
    )
    results = scheduler.compute()

    schedule = results[0]["data"]
    costs = results[1]["data"]
    costs_unit = results[1]["unit"]
    assert costs_unit == "EUR"

    # Check if constraints were met
    check_constraints(battery, schedule, soc_at_start)

    # Check for constant charging profile (minimizing the consumption breach)
    np.testing.assert_allclose(schedule, (1 - 0.4) / 24)

    # Check costs are correct
    # 60 EUR for 600 kWh consumption priced at 100 EUR/MWh
    np.testing.assert_almost_equal(costs["energy"], 100 * (1 - 0.4))
    # 24000 EUR for any 24 kW consumption breach priced at 1000 EUR/kW
    np.testing.assert_almost_equal(costs["any consumption breach"], 1000 * (25 - 1))
    # 24000 EUR for each 24 kW consumption breach per 15 minutes priced at 1000 EUR/kW
    np.testing.assert_almost_equal(
        costs["all consumption breaches"], 1000 * (25 - 1) * 96
    )
    # No production breaches
    np.testing.assert_almost_equal(costs["any production breach"], 0)
    np.testing.assert_almost_equal(costs["all production breaches"], 0 * 96)
    # 1.3 EUR for the 5 kW extra consumption peak priced at 260 EUR/MW
    np.testing.assert_almost_equal(costs["consumption peak"], 260 / 1000 * (25 - 20))
    # No production peak
    np.testing.assert_almost_equal(costs["production peak"], 0)
