import pandas as pd
from flexmeasures.data.services.scheduling import create_simultaneous_scheduling_job
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.models.time_series import Sensor


def test_create_simultaneous_jobs(db, app, flex_description_sequential, smart_building):
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

    jobs = create_simultaneous_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs=scheduler_specs,
        enqueue=False,
        **flex_description_sequential,
    )

    assert (
        len(jobs) == 1
    ), "There should be only 1 job for scheduling the system consisting of 2 devices."
    assert jobs[0].kwargs["asset_or_sensor"] == {
        "id": assets["Test Site"].id,
        "class": "GenericAsset",
    }
    assert jobs[0].kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
    ]

    ev_power = sensors["Test EV"].search_beliefs()
    battery_power = sensors["Test Battery"].search_beliefs()
    assert ev_power.empty
    assert battery_power.empty

    for job in jobs:
        queue.enqueue_job(job)

    work_on_rq(queue)
    jobs[0].perform()
    assert jobs[0].get_status() == "finished"

    # Get power values
    ev_power = sensors["Test EV"].search_beliefs()
    assert ev_power.sources.unique()[0].model == "StorageScheduler"
    ev_power = ev_power.droplevel([1, 2, 3])

    battery_power = sensors["Test Battery"].search_beliefs()
    assert battery_power.sources.unique()[0].model == "StorageScheduler"
    battery_power = battery_power.droplevel([1, 2, 3])

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

    # Resample prices to match power resolution
    prices = prices.resample("15min").ffill()

    start_charging = start + pd.Timedelta(hours=8)
    end_charging = start + pd.Timedelta(hours=10) - sensors["Test EV"].event_resolution

    # Assertions
    assert (ev_power.loc[start_charging:end_charging] != -0.005).values.any()  # 5 kW
    assert (
        battery_power.loc[start_charging:end_charging] != 0.005
    ).values.any()  # 5 kW

    # Calculate costs
    resolution = sensors["Test EV"].event_resolution.total_seconds() / 3600
    ev_costs = (ev_power * prices * resolution).sum().item()
    battery_costs = (battery_power * prices * resolution).sum().item()
    total_cost = ev_costs + battery_costs

    # Assert costs (using provided values)
    assert (
        round(ev_costs, 4) == -2.1625
    ), f"EV cost should be -2.1625 €, got {ev_costs} €"
    assert (
        battery_costs == 5.29
    ), f"Battery cost should be 5.29 €, got {battery_costs} €"
    assert (
        round(total_cost, 4) == 3.1275
    ), f"Total cost should be 3.1275 €, got {total_cost} €"
