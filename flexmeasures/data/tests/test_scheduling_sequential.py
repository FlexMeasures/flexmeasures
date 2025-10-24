from unittest.mock import patch
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException

import pandas as pd
from rq.job import Job
from flexmeasures.data.services.scheduling import create_sequential_scheduling_job
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.data.models.time_series import Sensor


def test_create_sequential_jobs(db, app, flex_description_sequential, smart_building):
    """Test sequential scheduling capabilities.

    It schedules the "Test Site", which contains two flexible devices and two inflexible devices.
    We verify that the pipeline creates the right number of jobs (two), corresponding to the inflexible devices,
    and an extra one which corresponds to the success callback job.
    """
    assets, sensors, soc_sensors = smart_building

    queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    end = pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam")

    scheduler_specs = {
        "module": "flexmeasures.data.models.planning.storage",
        "class": "StorageScheduler",
    }

    flex_description_sequential["start"] = start
    flex_description_sequential["end"] = end

    create_sequential_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs=scheduler_specs,
        enqueue=True,
        **flex_description_sequential,
    )

    # There should be 3 jobs:
    # 2 jobs scheduling the 2 flexible devices in the flex-model, plus 1 'done job' to wrap things up
    queued_jobs = app.queues["scheduling"].jobs
    deferred_jobs = [
        Job.fetch(job_id, connection=queue.connection)
        for job_id in app.queues["scheduling"].deferred_job_registry.get_job_ids()
    ]
    # Sort deferred_jobs by their created_at attribute
    deferred_jobs = sorted(deferred_jobs, key=lambda job: job.created_at)
    assert (
        len(queued_jobs) == 1
    ), "Only the job for scheduling the first device sequentially should be queued."
    assert (
        len(deferred_jobs) == 2
    ), "The job for scheduling the second device, and the wrap-up job, should be deferred."

    # The EV is scheduled firstly.
    assert queued_jobs[0].kwargs["asset_or_sensor"] == {
        "id": sensors["Test EV"].id,
        "class": "Sensor",
    }
    # It uses the inflexible-device-sensors that are defined in the flex-context, exclusively.
    assert queued_jobs[0].kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
    ]

    # The Battery is scheduled secondly (i.e. the first deferred job).
    assert deferred_jobs[0].kwargs["asset_or_sensor"] == {
        "id": sensors["Test Battery"].id,
        "class": "Sensor",
    }
    # In addition to the inflexible devices already present in the flex-context (PV and Building), the power sensor of the EV is included.
    assert deferred_jobs[0].kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
        sensors["Test EV"].id,
    ]

    ev_power = sensors["Test EV"].search_beliefs()
    battery_power = sensors["Test Battery"].search_beliefs()

    # Sensors are empty before running the schedule
    assert ev_power.empty
    assert battery_power.empty

    # Work on jobs
    queued_jobs[0].perform()
    work_on_rq(queue, handle_scheduling_exception)

    # Check that the jobs completed successfully
    assert queued_jobs[0].get_status() == "finished"
    assert deferred_jobs[0].get_status() == "finished"
    assert deferred_jobs[1].get_status() == "finished"

    # check results
    ev_power = sensors["Test EV"].search_beliefs()
    assert ev_power.sources.unique()[0].model == "StorageScheduler"
    ev_power = ev_power.droplevel([1, 2, 3])

    battery_power = sensors["Test Battery"].search_beliefs()
    assert battery_power.sources.unique()[0].model == "StorageScheduler"
    battery_power = battery_power.droplevel([1, 2, 3])

    start_charging = start + pd.Timedelta(hours=8)
    end_charging = start + pd.Timedelta(hours=10) - sensors["Test EV"].event_resolution

    assert (ev_power.loc[start_charging:end_charging] == -0.005).values.all()  # 5 kW
    assert (
        battery_power.loc[start_charging:end_charging] == 0.005
    ).values.all()  # 5 kW

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

    # Calculate costs
    resolution = sensors["Test EV"].event_resolution.total_seconds() / 3600
    ev_costs = (-ev_power * prices * resolution).sum().item()
    battery_costs = (-battery_power * prices * resolution).sum().item()
    total_cost = ev_costs + battery_costs

    # Assert costs
    assert ev_costs == 2.2375, f"EV cost should be 2.2375 €, got {ev_costs} €"
    assert (
        battery_costs == -4.415
    ), f"Battery cost should be -4.415 €, got {battery_costs} €"
    assert total_cost == -2.1775, f"Total cost should be -2.1775 €, got {total_cost} €"


def test_create_sequential_jobs_fallback(
    db, app, flex_description_sequential, smart_building
):
    """Test fallback scheduler in a chain of sequential scheduling (sub)jobs.

    Checks execution of a sequential scheduling job, where 1 of the subjobs is set up to fail and trigger its fallback.
    The deferred subjobs should still succeed after the fallback succeeds, even though the first subjob fails.
    """
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

    storage_module = "flexmeasures.data.models.planning.storage"

    with patch(f"{storage_module}.StorageScheduler.persist_flex_model"):
        with patch(f"{storage_module}.StorageFallbackScheduler.persist_flex_model"):
            with patch(
                f"{storage_module}.StorageScheduler.compute",
                side_effect=iter([InfeasibleProblemException(), [], []]),
            ):
                create_sequential_scheduling_job(
                    asset=assets["Test Site"],
                    scheduler_specs=scheduler_specs,
                    enqueue=True,
                    force_new_job_creation=True,  # otherwise the cache might kick in due to sub-jobs already created in other tests
                    **flex_description_sequential,
                )

                # There should be 3 jobs:
                # 2 jobs scheduling the 2 flexible devices in the flex-model, plus 1 'done job' to wrap things up
                queued_jobs = app.queues["scheduling"].jobs
                deferred_jobs = [
                    Job.fetch(job_id, connection=queue.connection)
                    for job_id in app.queues[
                        "scheduling"
                    ].deferred_job_registry.get_job_ids()
                ]
                # Sort deferred_jobs by their created_at attribute
                deferred_jobs = sorted(deferred_jobs, key=lambda job: job.created_at)
                assert (
                    len(queued_jobs) == 1
                ), "Only the job for scheduling the first device sequentially should be queued."
                assert (
                    len(deferred_jobs) == 2
                ), "The job for scheduling the second device, and the wrap-up job, should be deferred."

                # Work on jobs
                work_on_rq(queue, exc_handler=handle_scheduling_exception)

                # Refresh jobs so that the fallback_job_id (which should be set by now) can be read
                for job in queued_jobs:
                    job.refresh()

                finished_jobs = queue.finished_job_registry.get_job_ids()
                failed_jobs = queue.failed_job_registry.get_job_ids()

                # Original job failed
                assert queued_jobs[0].id in failed_jobs

                # The fallback job ran successfully
                assert queued_jobs[0].meta["fallback_job_id"] in finished_jobs

                # The deferred jobs ran successfully
                assert deferred_jobs[0].id in finished_jobs
                assert deferred_jobs[1].id in finished_jobs
