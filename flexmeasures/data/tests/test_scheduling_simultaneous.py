import pytest

import pandas as pd
from flexmeasures.data.services.scheduling import create_simultaneous_scheduling_job
from flexmeasures.data.tests.utils import work_on_rq


@pytest.mark.parametrize("use_heterogeneous_resolutions", [True, False])
def test_create_simultaneous_jobs(
    db, app, flex_description_sequential, smart_building, use_heterogeneous_resolutions
):
    assets, sensors = smart_building
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
        "class": "GenericAsset",
    }
    # It uses the inflexible-device-sensors that are defined in the flex-context, exclusively.
    assert job.kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
    ]

    ev_power = sensors["Test EV"].search_beliefs()
    battery_power = sensors["Test Battery"].search_beliefs()

    # sensors are empty before running the schedule
    assert ev_power.empty
    assert battery_power.empty

    # work tasks
    work_on_rq(queue)

    # check that the jobs complete successfully
    job.perform()
    assert job.get_status() == "finished"

    # check results
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

    start_charging = start + pd.Timedelta(hours=10)
    end_charging = start + pd.Timedelta(hours=15) - sensors["Test EV"].event_resolution

    assert all(ev_power.loc[start_charging:end_charging] == -0.01)  # 10 kW
    assert all(battery_power.loc[start_charging:end_charging] == 0.01)  # 10 kW
