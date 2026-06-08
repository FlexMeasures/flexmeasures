import pytest

import numpy as np
import pandas as pd
from flexmeasures.data.services.scheduling import create_simultaneous_scheduling_job
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("use_heterogeneous_resolutions", [True, False])
def test_create_simultaneous_jobs(
    db, app, flex_description_sequential, smart_building, use_heterogeneous_resolutions
):
    assets, sensors, soc_sensors = smart_building
    queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    end = pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam")

    scheduler_specs = {
        "module": "flexmeasures.data.models.planning.storage",
        "class": "StorageScheduler",
    }
    flex_description_sequential["flex_model"][0]["sensor_flex_model"][
        "state-of-charge"
    ] = {"sensor": soc_sensors["Test EV"].id}
    if use_heterogeneous_resolutions:
        flex_description_sequential["flex_model"][1]["sensor_flex_model"][
            "state-of-charge"
        ] = {"sensor": soc_sensors["Test Battery 1h"].id}
    else:
        flex_description_sequential["flex_model"][1]["sensor_flex_model"][
            "state-of-charge"
        ] = {"sensor": soc_sensors["Test Battery"].id}

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
    ev_soc = soc_sensors["Test EV"].search_beliefs()
    if use_heterogeneous_resolutions:
        battery_power = sensors["Test Battery 1h"].search_beliefs()
        battery_soc = soc_sensors["Test Battery 1h"].search_beliefs()
    else:
        battery_power = sensors["Test Battery"].search_beliefs()
        battery_soc = soc_sensors["Test Battery"].search_beliefs()
    assert ev_power.empty
    assert ev_soc.empty
    assert battery_power.empty
    assert battery_soc.empty

    # work tasks
    work_on_rq(queue)

    # check that the jobs complete successfully
    job.perform()
    assert job.get_status() == "finished"

    # Get power and SoC values
    ev_power = sensors["Test EV"].search_beliefs()
    assert ev_power.sources.unique()[0].model == "StorageScheduler"
    ev_soc = soc_sensors["Test EV"].search_beliefs()
    assert ev_soc.sources.unique()[0].model == "StorageScheduler"

    if use_heterogeneous_resolutions:
        battery_power = sensors["Test Battery 1h"].search_beliefs()
        assert len(battery_power) == 24
        battery_soc = soc_sensors["Test Battery 1h"].search_beliefs()
        assert len(battery_soc) == 97
    else:
        battery_power = sensors["Test Battery"].search_beliefs()
        assert len(battery_power) == 96
        battery_soc = soc_sensors["Test Battery"].search_beliefs()
        assert len(battery_soc) == 97

    ev_power = ev_power.droplevel([1, 2, 3])
    assert battery_power.sources.unique()[0].model == "StorageScheduler"
    battery_power = battery_power.droplevel([1, 2, 3])

    # Check schedules
    # start_charging = start + pd.Timedelta(hours=8)
    # end_charging = start + pd.Timedelta(hours=10) - sensors["Test EV"].event_resolution
    # assert (
    #     ev_power.loc[start_charging:end_charging] != -0.005
    # ).values.any(), "no charging at full device power capacity (5 kW) expected,
    for target_no in (1, 2, 3):
        non_zero_target = flex_description_sequential["flex_model"][0][
            "sensor_flex_model"
        ]["soc-targets"][target_no]
        # NB: assumes perfect conversion and storage efficiencies
        np.testing.assert_approx_equal(
            # head(-1) because ev_power is indexed by event start and target datetime corresponds to event end
            # minus ev_power because ev_power uses negative values for consumption
            -ev_power[: non_zero_target["datetime"]].head(-1).sum().item() / 4,
            non_zero_target["value"],
        )

    # Get price data
    price_sensor_id = flex_description_sequential["flex_context"][
        "consumption-price-sensor"
    ]
    price_sensor = db.session.get(Sensor, price_sensor_id)
    prices = price_sensor.search_beliefs(
        event_starts_after=start, event_ends_before=end
    )
    prices = prices.droplevel([1, 2, 3])
    prices.index = prices.index.tz_convert("Europe/Amsterdam")

    # Calculate costs
    ev_costs = (-ev_power.resample("1h").mean() * prices).sum().item()
    battery_costs = (-battery_power.resample("1h").mean() * prices).sum().item()
    total_cost = ev_costs + battery_costs

    # Define expected costs based on resolution
    expected_total_cost = -5.7025
    expected_ev_costs = 2.2375
    expected_battery_costs = expected_total_cost - expected_ev_costs

    # Check costs
    np.testing.assert_approx_equal(
        total_cost,
        expected_total_cost,
        4,
        f"Total costs should be €{expected_total_cost}, got €{total_cost}",
    )
    np.testing.assert_approx_equal(
        ev_costs,
        expected_ev_costs,
        4,
        f"EV costs should be €{expected_ev_costs}, got €{ev_costs}",
    )
    np.testing.assert_approx_equal(
        battery_costs,
        expected_battery_costs,
        4,
        f"Battery costs should be €{expected_battery_costs}, got €{battery_costs}",
    )
    np.testing.assert_approx_equal(
        job.meta["scheduler_info"]["commitment_costs"]["electricity net energy"],
        expected_total_cost,
        4,
        "Reported costs should match our expectation",
    )
