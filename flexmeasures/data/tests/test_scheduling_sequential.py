from unittest.mock import patch
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException

import pandas as pd
from rq.job import Job
from sqlalchemy.exc import PendingRollbackError
from flexmeasures.data.services.scheduling import (
    _describe_scheduled_device,
    create_sequential_scheduling_job,
)
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.data.services.utils import failed_job_reason, sort_jobs
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
    assert deferred_jobs[1].meta["asset_or_sensor"] == {
        "id": assets["Test Site"].id,
        "class": "Asset",
    }

    ev_power = sensors["Test EV"].search_beliefs()
    battery_power = sensors["Test Battery"].search_beliefs()

    # Sensors are empty before running the schedule
    assert ev_power.empty
    assert battery_power.empty

    # Work on jobs
    queued_jobs[0].perform()
    work_on_rq(queue, handle_scheduling_exception)

    # Check that the jobs completed successfully
    ev_job = queued_jobs[0]
    battery_job = deferred_jobs[0]
    wrapup_job = deferred_jobs[1]
    assert ev_job.get_status() == "finished"
    assert battery_job.get_status() == "finished"
    assert wrapup_job.get_status() == "finished"

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

    # Assert costs
    expected_ev_costs = 2.2375
    expected_battery_costs = -4.415
    assert (
        ev_costs == expected_ev_costs
    ), f"EV cost should be {expected_ev_costs} €, got {ev_costs} €"
    assert (
        battery_costs == expected_battery_costs
    ), f"Battery cost should be {expected_battery_costs} €, got {battery_costs} €"

    # todo: the ev job has scheduler_info and commitment costs, but the battery job has not
    #       Here, we want to check the electricity costs of the battery job, which takes into account the EV
    # expected_total_cost = expected_ev_costs + expected_battery_costs
    # np.testing.assert_approx_equal(
    #     battery_job.meta["scheduler_info"]["commitment_costs"]["electricity net energy"],
    #     expected_total_cost,
    #     4,
    #     f"Reported costs should match our expectation",
    # )


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


def test_describe_scheduled_device_survives_an_unusable_session(
    db, app, smart_building
):
    """Naming the device must not raise when the database session is unusable.

    A job that failed on a database error leaves the session needing a rollback. If naming its device raised,
    the failure would never be cascaded to the dependent jobs, and the chain would wedge after all.
    """
    _, sensors, _ = smart_building
    sensor = sensors["Test EV"]
    reference = {"id": sensor.id, "class": "Sensor"}

    assert (
        _describe_scheduled_device(reference)
        == f"sensor {sensor.id} ({sensor.generic_asset.name} - {sensor.name})"
    )

    with patch(
        "flexmeasures.data.services.scheduling.get_asset_or_sensor_from_ref",
        side_effect=PendingRollbackError("session needs rollback", None, None),
    ):
        assert _describe_scheduled_device(reference) == f"sensor {sensor.id}"


def test_create_sequential_jobs_fallback_for_last_device(
    db, app, flex_description_sequential, smart_building
):
    """Test the fallback scheduler kicking in for the last device in a chain of sequential scheduling (sub)jobs.

    The wrap-up job depends on that last subjob directly, so it must stay deferred while the fallback job is pending.
    Were it queued alongside the fallback job, a second worker could run it right away, find a device without a schedule,
    and report the chain as failed just before the fallback schedules that device after all.
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
            # The first device is scheduled fine, the last one is infeasible and falls back
            with patch(
                f"{storage_module}.StorageScheduler.compute",
                side_effect=iter([[], InfeasibleProblemException(), []]),
            ):
                create_sequential_scheduling_job(
                    asset=assets["Test Site"],
                    scheduler_specs=scheduler_specs,
                    enqueue=True,
                    force_new_job_creation=True,  # otherwise the cache might kick in due to sub-jobs already created in other tests
                    **flex_description_sequential,
                )

                queued_jobs = queue.jobs
                deferred_jobs = sort_jobs(
                    queue, queue.deferred_job_registry.get_job_ids()
                )
                assert len(queued_jobs) == 1
                assert len(deferred_jobs) == 2
                battery_job, wrapup_job = deferred_jobs

                # Work until the last subjob has failed and triggered its fallback, but no further
                work_on_rq(queue, exc_handler=handle_scheduling_exception, max_jobs=2)

                battery_job.refresh()
                wrapup_job.refresh()
                fallback_job_id = battery_job.meta["fallback_job_id"]
                assert battery_job.get_status() == "failed"
                assert fallback_job_id in [job.id for job in queue.jobs]

                # The wrap-up job must not be runnable while the fallback job is still pending
                assert wrapup_job.get_status() == "deferred", (
                    "The wrap-up job should still be waiting for the fallback job, "
                    f"but it is {wrapup_job.get_status()}."
                )

                # Now let the fallback job (and, after it, the wrap-up job) run
                work_on_rq(queue, exc_handler=handle_scheduling_exception)

    finished_jobs = queue.finished_job_registry.get_job_ids()

    # The last subjob failed, but its fallback scheduled the device after all
    assert fallback_job_id in finished_jobs

    # So the chain succeeded, and the wrap-up job should not report a failure
    assert wrapup_job.id in finished_jobs, (
        "The wrap-up job should have waited for the fallback job to finish, "
        f"but it is {wrapup_job.get_status()}: {failed_job_reason(Job.fetch(wrapup_job.id, connection=queue.connection))}"
    )


def test_create_sequential_jobs_without_fallback(
    db, app, flex_description_sequential, smart_building
):
    """Test that a failing subjob without a fallback scheduler does not wedge the chain.

    The first device is infeasible, and its scheduler has no fallback. The remaining subjobs can then never run,
    so they should be failed rather than left deferred, and the wrap-up job — whose id is what the trigger endpoint hands to the client —
    should reach a terminal failed state naming the device that could not be scheduled.
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
        # Retire the fallback scheduler, like ProcessScheduler and custom schedulers do by default
        with patch(f"{storage_module}.StorageScheduler.fallback_scheduler_class", None):
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

                queued_jobs = queue.jobs
                deferred_jobs = sort_jobs(
                    queue, queue.deferred_job_registry.get_job_ids()
                )
                assert len(queued_jobs) == 1
                assert len(deferred_jobs) == 2
                ev_job = queued_jobs[0]
                battery_job, wrapup_job = deferred_jobs

                # Work on jobs
                work_on_rq(queue, exc_handler=handle_scheduling_exception)

    failed_jobs = queue.failed_job_registry.get_job_ids()

    # The EV subjob failed, and had no fallback to fall back on
    assert ev_job.id in failed_jobs
    ev_job.refresh()
    assert "fallback_job_id" not in ev_job.meta

    # The battery subjob can never run, so it was failed rather than left deferred
    assert battery_job.id in failed_jobs
    assert battery_job.get_status() == "failed"

    # The wrap-up job ran, and failed while naming the device that could not be scheduled
    assert wrapup_job.id in failed_jobs
    assert wrapup_job.get_status() == "failed"
    reason = failed_job_reason(Job.fetch(wrapup_job.id, connection=queue.connection))
    assert f"sensor {sensors['Test EV'].id} (Test EV - power)" in reason
    assert "InfeasibleProblemException" in reason

    # No job is left waiting on a chain that will never complete
    assert queue.deferred_job_registry.get_job_ids() == []


def test_create_sequential_jobs_with_sign_explicit_context(
    db, app, flex_description_sequential, smart_building
):
    """When the site's flex-context uses the sign-explicit inflexible fields,
    previously scheduled sensors are injected as sensor references, routed by
    their consumption_is_positive attribute (all fixture sensors default to
    production-positive), without touching the deprecated field.
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
    flex_context = flex_description_sequential["flex_context"]
    inflexible_sensor_ids = flex_context.pop("inflexible-device-sensors")
    flex_context["inflexible-production"] = [
        {"sensor": sensor_id} for sensor_id in inflexible_sensor_ids
    ]

    create_sequential_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs=scheduler_specs,
        enqueue=True,
        **flex_description_sequential,
    )

    queued_jobs = app.queues["scheduling"].jobs
    deferred_jobs = [
        Job.fetch(job_id, connection=queue.connection)
        for job_id in app.queues["scheduling"].deferred_job_registry.get_job_ids()
    ]
    deferred_jobs = sorted(deferred_jobs, key=lambda job: job.created_at)

    # The EV is scheduled firstly, using only the user-given inflexible devices.
    assert queued_jobs[0].kwargs["flex_context"]["inflexible-production"] == [
        {"sensor": sensors["Test Solar"].id},
        {"sensor": sensors["Test Building"].id},
    ]
    assert "inflexible-device-sensors" not in queued_jobs[0].kwargs["flex_context"]

    # The Battery is scheduled secondly, with the EV's sensor injected as an
    # inflexible device (production-positive: the EV sensor carries no
    # consumption_is_positive attribute).
    assert deferred_jobs[0].kwargs["flex_context"]["inflexible-production"] == [
        {"sensor": sensors["Test Solar"].id},
        {"sensor": sensors["Test Building"].id},
        {"sensor": sensors["Test EV"].id},
    ]
    assert "inflexible-device-sensors" not in deferred_jobs[0].kwargs["flex_context"]
