from unittest.mock import patch
from flexmeasures.data.models.planning.exceptions import InfeasibleProblemException

import pandas as pd
from rq.job import Job
from sqlalchemy import select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.scheduling import create_sequential_scheduling_job
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.scheduling import handle_scheduling_exception
from flexmeasures.data.models.time_series import Sensor


def test_sequential_jobs_carry_the_request_config_not_a_data_source_id(
    db, app, flex_description_sequential, smart_building
):
    """The device jobs of one request share a data source, without depending on an uncommitted row.

    FlexMeasures does not auto-commit the session of the request that enqueues the jobs
    (see `flexmeasures.data.transactional`), so a data source created while enqueueing would never reach the workers.
    The jobs therefore carry the request's configuration, and each worker resolves the source from it and commits.
    """
    assets, sensors, soc_sensors = smart_building
    queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    flex_description_sequential["start"] = start
    flex_description_sequential["end"] = pd.Timestamp("2015-01-04").tz_localize(
        "Europe/Amsterdam"
    )

    scheduler_sources_before = db.session.scalars(
        select(DataSource).filter_by(type="scheduler")
    ).all()

    create_sequential_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs={
            "module": "flexmeasures.data.models.planning.storage",
            "class": "StorageScheduler",
        },
        enqueue=True,
        **flex_description_sequential,
    )

    device_jobs = [
        Job.fetch(job_id, connection=queue.connection)
        for job_id in queue.job_ids
        if Job.fetch(job_id, connection=queue.connection).kwargs.get("asset_or_sensor")
    ]
    assert device_jobs, "the request should have queued a job per device"
    configs = [job.kwargs.get("data_source_config") for job in device_jobs]
    assert all(
        config is not None for config in configs
    ), "every device job should carry the request's configuration"
    assert all(
        config == configs[0] for config in configs
    ), "the device jobs of one request describe one configuration, so they share one data source"
    assert "data_source_id" not in device_jobs[0].kwargs

    # Enqueueing wrote no data source of its own, which is what it must not rely on.
    assert (
        db.session.scalars(select(DataSource).filter_by(type="scheduler")).all()
        == scheduler_sources_before
    )

    # This test never runs the jobs it queued, so clear Redis rather than leaking them into the next test:
    # the queue and its deferred registry, the jobs themselves, whose ids are derived from what they schedule,
    # and the job cache, which would otherwise skip the next test's identical request as already made.
    app.redis_connection.flushdb()


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


def test_create_sequential_jobs_without_storage_fallback(
    db, app, flex_description_sequential, smart_building
):
    """Test an infeasible first subjob in a chain of sequential scheduling jobs.

    Checks that no storage fallback job is created. The deferred subjobs should remain
    deferred because the first subjob failed.
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
        with patch(
            f"{storage_module}.StorageScheduler.compute",
            side_effect=InfeasibleProblemException(),
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

            for job in queued_jobs:
                job.refresh()
            for job in deferred_jobs:
                job.refresh()

            finished_jobs = queue.finished_job_registry.get_job_ids()
            failed_jobs = queue.failed_job_registry.get_job_ids()

            # Original job failed and no fallback job was created
            assert queued_jobs[0].id in failed_jobs
            assert queued_jobs[0].meta.get("fallback_job_id") is None

            # The deferred jobs should not run when their dependency fails without fallback
            assert deferred_jobs[0].id not in finished_jobs
            assert deferred_jobs[1].id not in finished_jobs

    # Without a fallback to unblock the chain, the deferred subjobs stay deferred
    # for good, so clear them here rather than leaking them into the next test.
    for deferred_job_id in queue.deferred_job_registry.get_job_ids():
        queue.deferred_job_registry.remove(deferred_job_id)
    queue.empty()


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
