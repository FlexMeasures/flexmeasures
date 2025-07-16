import pytest

import numpy as np
import pandas as pd
from flexmeasures.data.services.scheduling import create_simultaneous_scheduling_job
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("use_heterogeneous_resolutions", [True, False])
def test_create_simultaneous_jobs(
    db, app, flex_description_sequential, smart_building, use_heterogeneous_resolutions
):
    assets, sensors, _ = smart_building
    queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    end = pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam")

    scheduler_specs = {
        "module": "flexmeasures.data.models.planning.storage",
        "class": "StorageScheduler",
    }

    flex_description_sequential["start"] = start
    flex_description_sequential["end"] = end
    if use_heterogeneous_resolutions:
        flex_description_sequential["flex_model"][1]["sensor"] = sensors[
            "Test Battery 1h"
        ]

    job = create_simultaneous_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs=scheduler_specs,
        enqueue=True,
        **flex_description_sequential,
    )

    # The EV is scheduled firstly.
    assert job.kwargs["asset_or_sensor"] == {
        "id": assets["Test Site"].id,
        "class": "Asset",
    }
    # It uses the inflexible-device-sensors that are defined in the flex-context, exclusively.
    assert job.kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
    ]

    ev_power = sensors["Test EV"].search_beliefs()
    battery_power = sensors["Test Battery"].search_beliefs()
    assert ev_power.empty
    assert battery_power.empty

    # work tasks
    work_on_rq(queue)

    # check that the jobs complete successfully
    job.perform()
    assert job.get_status() == "finished"

    # Get power values
    ev_power = sensors["Test EV"].search_beliefs()
    assert ev_power.sources.unique()[0].model == "StorageScheduler"
    ev_power = ev_power.droplevel([1, 2, 3])

    if use_heterogeneous_resolutions:
        battery_power = sensors["Test Battery 1h"].search_beliefs()
        assert len(battery_power) == 24
    else:
        battery_power = sensors["Test Battery"].search_beliefs()
        assert len(battery_power) == 96
    assert battery_power.sources.unique()[0].model == "StorageScheduler"
    battery_power = battery_power.droplevel([1, 2, 3])
    start_charging = start + pd.Timedelta(hours=8)
    end_charging = start + pd.Timedelta(hours=10) - sensors["Test EV"].event_resolution

    # Check schedules
    assert (
        ev_power.loc[start_charging:end_charging] != -0.005
    ).values.any(), "no charging at full device power capacity (5 kW) expected"
    for target_no in (1, 2, 3):
        non_zero_target = flex_description_sequential["flex_model"][0][
            "sensor_flex_model"
        ]["soc-targets"][target_no]
        # NB: assumes perfect conversion and storage efficiencies
        np.testing.assert_approx_equal(
            # head(-1) because ev_power is indexed by event start and target datetime corresponds to event end
            # minus ev_power because ev_power uses negative values for consumption
            -ev_power[: non_zero_target["datetime"]].head(-1).sum()[0] / 4,
            non_zero_target["value"],
        )

    # Get price data
    price_sensor_id = flex_description_sequential["flex_context"][
        "consumption-price-sensor"
    ]
    price_sensor = db.session.get(Sensor, price_sensor_id)
    prices = price_sensor.search_beliefs(
        event_starts_after=start - pd.Timedelta(hours=1), event_ends_before=end
    )
    prices = prices.droplevel([1, 2, 3])
    prices.index = prices.index.tz_convert("Europe/Amsterdam")

    # Calculate costs
    ev_costs = (-ev_power.resample("1h").mean() * prices).sum().item()
    battery_costs = (-battery_power.resample("1h").mean() * prices).sum().item()
    total_cost = ev_costs + battery_costs

    # Define expected costs based on resolution
    expected_ev_costs = 2.2375
    expected_battery_costs = -5.515
    expected_total_cost = -3.2775

    # Check costs
    assert (
        round(total_cost, 4) == expected_total_cost
    ), f"Total costs should be €{expected_total_cost}, got €{total_cost}"

    assert (
        round(ev_costs, 4) == expected_ev_costs
    ), f"EV costs should be €{expected_ev_costs}, got €{ev_costs}"

    assert (
        round(battery_costs, 4) == expected_battery_costs
    ), f"Battery costs should be €{expected_battery_costs}, got €{battery_costs}"
