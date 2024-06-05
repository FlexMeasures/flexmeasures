import pandas as pd
from flexmeasures.data.services.scheduling import create_sequential_scheduling_job

# from flexmeasures.data.tests.utils import work_on_rq, exception_reporter


def test_create_sequential_jobs(db, app, flex_description_sequential, smart_building):
    assets, sensors = smart_building
    # queue = app.queues["scheduling"]
    start = pd.Timestamp("2015-01-03").tz_localize("Europe/Amsterdam")
    end = pd.Timestamp("2015-01-04").tz_localize("Europe/Amsterdam")

    scheduler_specs = {
        "module": "flexmeasures.data.models.planning.storage",
        "class": "StorageScheduler",
    }

    flex_description_sequential["start"] = start.isoformat()
    flex_description_sequential["end"] = end.isoformat()

    jobs = create_sequential_scheduling_job(
        asset=assets["Test Site"],
        scheduler_specs=scheduler_specs,
        enqueue=False,
        **flex_description_sequential,
    )

    assert (
        len(jobs) == 3
    ), "There should be 3 jobs: 2 jobs scheduling the 2 flexible devices in the flex-model, plus 1 'done job' to wrap things up."

    # The EV is scheduled firstly.
    assert jobs[0].kwargs["asset_or_sensor"] == {
        "id": sensors["Test EV"].id,
        "class": "Sensor",
    }
    # It uses the inflexible-device-sensors that are defined in the flex-context, exclusively.
    assert jobs[0].kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
    ]

    # The Battery is scheduled secondly.
    assert jobs[1].kwargs["asset_or_sensor"] == {
        "id": sensors["Test Battery"].id,
        "class": "Sensor",
    }
    # In addition to the inflexible devices already present in the flex-context (PV and Building), the power sensor of the EV is included.
    assert jobs[1].kwargs["flex_context"]["inflexible-device-sensors"] == [
        sensors["Test Solar"].id,
        sensors["Test Building"].id,
        sensors["Test EV"].id,
    ]

    # TODO: enqueue jobs, let them run and check results
    # for job in jobs:
    #     queue.enqueue_job(job)

    # work_on_rq(queue, exc_handler=exception_reporter)
