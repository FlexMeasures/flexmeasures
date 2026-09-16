from __future__ import annotations

from datetime import datetime, timedelta, timezone

import isodate
import pytest
from rq.job import Job
from sqlalchemy.exc import IntegrityError

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.automations import Automation, AutomationRun
from flexmeasures.data.services.automations import resolve_schedule_generator
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.automations import (
    get_automations_feeding_sensor,
    get_automation_job_stats,
    resolve_automation_sensors,
    run_automation,
)


def build_schedule_automation(asset, **kwargs) -> Automation:
    """Build a schedule automation, with the data generator that its creation and its runs resolve.

    A schedule automation's generator describes the scheduler the asset resolves to, and the flex config it computes under,
    so it is derived from the asset and the parameters rather than chosen.
    """
    automation = Automation(asset=asset, type="scheduling", **kwargs)
    automation.generator_id = resolve_schedule_generator(
        asset.id, automation.parameters
    ).id
    return automation


@pytest.fixture()
def automation_with_generator(fresh_db):
    asset_type = GenericAssetType(name="automation test asset type")
    asset = GenericAsset(name="automation test asset", generic_asset_type=asset_type)
    generator = DataSource(
        name="automation test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automation = Automation(
        asset=asset,
        generator=generator,
        type="forecasting",
        name="automation generator lifecycle test",
        cronstr="0 6 * * *",
        parameters={},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()
    return automation, generator


def test_referenced_automation_generator_cannot_be_deleted(
    fresh_db, automation_with_generator
):
    automation, generator = automation_with_generator
    automation_id = automation.id
    generator_id = generator.id

    fresh_db.session.delete(generator)
    with pytest.raises(IntegrityError):
        fresh_db.session.commit()
    fresh_db.session.rollback()

    persisted_automation = fresh_db.session.get(Automation, automation_id)
    assert persisted_automation is not None
    assert persisted_automation.generator_id == generator_id
    assert fresh_db.session.get(DataSource, generator_id) is not None

    fresh_db.session.delete(persisted_automation)
    fresh_db.session.commit()
    persisted_generator = fresh_db.session.get(DataSource, generator_id)
    fresh_db.session.delete(persisted_generator)
    fresh_db.session.commit()
    assert fresh_db.session.get(DataSource, generator_id) is None


def test_automation_requires_generator(fresh_db, automation_with_generator):
    automation, _ = automation_with_generator
    automation.generator = None

    with pytest.raises(IntegrityError):
        fresh_db.session.commit()


def test_schedule_automation_generator_describes_its_scheduler_and_config(
    fresh_db, automation_with_generator
):
    """A schedule automation's generator names the scheduler, and records the flex config it computes under."""
    forecast_automation, _ = automation_with_generator
    schedule_automation = build_schedule_automation(
        forecast_automation.asset,
        name="scheduling the asset",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H"},
    )
    fresh_db.session.add(schedule_automation)
    fresh_db.session.commit()

    generator = schedule_automation.generator
    assert generator is not None
    assert generator.type == "scheduler"
    assert generator.model == "StorageScheduler"
    config = generator.attributes["data_generator"]["config"]
    assert config["asset"] == forecast_automation.asset.id
    # The flex config is recorded as the asset tree and the trigger message spell it, not as timing.
    assert set(config) == {"asset", "flex-model", "flex-context"}


@pytest.fixture()
def clean_scheduling_redis(app):
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


def test_run_schedule_automation(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
    add_market_prices_fresh_db,
    clean_scheduling_redis,
):
    """A schedules automation queues a scheduling job carrying trigger meta data."""
    battery = add_battery_assets_fresh_db["Test battery"]
    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = battery.sensors[0].id

    automation = build_schedule_automation(
        battery,
        name="Nightly schedules",
        cronstr="0 0 * * *",
        parameters={**message, "flex-model": [flex_model]},
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()

    returns = run_automation(automation)
    assert returns["n_jobs"] == 1

    job = Job.fetch(returns["job_id"], connection=app.queues["scheduling"].connection)
    assert job.meta["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
    }


def test_a_durable_run_schedules_what_it_was_planned_with(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
    add_market_prices_fresh_db,
    clean_scheduling_redis,
):
    """A run dispatched from its own record schedules its stored parameters, and names itself on the job.

    The automation's parameters may have moved on since the run was planned,
    so a retry must re-queue the run's plan rather than today's settings.
    """
    battery = add_battery_assets_fresh_db["Test battery"]
    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = battery.sensors[0].id
    planned_parameters = {**message, "flex-model": [flex_model]}

    automation = build_schedule_automation(
        battery,
        name="Nightly schedules",
        cronstr="0 0 * * *",
        parameters=planned_parameters,
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()
    run = AutomationRun(
        automation=automation,
        scheduled_at=datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
        schedule_revision=automation.schedule_revision,
        automation_type=automation.type,
        generator_id=automation.generator_id,
        dispatch_state="claimed",
        execution_state="pending",
        parameters=planned_parameters,
        plan={},
    )
    fresh_db.session.add(run)
    fresh_db.session.flush()
    # The automation is edited after the run was planned, to a duration the run must not pick up.
    automation.parameters = {**planned_parameters, "duration": "PT6H"}
    fresh_db.session.flush()

    returns = run_automation(automation, automation_run=run)

    job = Job.fetch(returns["job_id"], connection=app.queues["scheduling"].connection)
    assert job.meta["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
        "automation_run_id": run.id,
    }
    assert job.kwargs["end"] - job.kwargs["start"] == isodate.parse_duration(
        planned_parameters["duration"]
    )


@pytest.mark.parametrize("sequential", (False, True))
def test_run_minimal_schedule_automation_with_stored_flex_config(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
    add_market_prices_fresh_db,
    clean_scheduling_redis,
    sequential,
):
    """A minimal trigger inherits a single device's flex config from the asset tree."""
    battery = add_battery_assets_fresh_db["Test battery"]
    building = battery.parent_asset
    power_sensor = next(sensor for sensor in battery.sensors if sensor.name == "power")
    battery.flex_model = {
        "consumption": {"sensor": power_sensor.id},
        "soc-at-start": "2.5 MWh",
        "soc-min": "0 MWh",
        "soc-max": "5 MWh",
        "power-capacity": "2 MW",
    }
    automation = build_schedule_automation(
        building,
        name="Minimal stored-flex schedule",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H", "sequential": sequential},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    returns = run_automation(automation)
    job = Job.fetch(returns["job_id"], connection=app.redis_connection)

    if sequential:
        assert returns["n_jobs"] == 2
        device_job = Job.fetch(job.args[0][0], connection=app.redis_connection)
        assert device_job.meta["asset_or_sensor"] == {
            "id": power_sensor.id,
            "class": "Sensor",
        }
    else:
        assert returns["n_jobs"] == 1
        assert job.meta["asset_or_sensor"] == {"id": building.id, "class": "Asset"}


def test_schedule_automation_follows_its_asset_flex_config(
    fresh_db,
    app,
    add_battery_assets_fresh_db,
    add_market_prices_fresh_db,
    clean_scheduling_redis,
):
    """Editing the asset's flex config moves the automation to another data generator.

    A schedule automation's generator describes the flex config the scheduler computes under,
    and that config is the trigger message merged with what the asset tree stores,
    so a change to the asset shows up as a different generator on the automation's next run.
    """
    battery = add_battery_assets_fresh_db["Test battery"]
    building = battery.parent_asset
    power_sensor = next(sensor for sensor in battery.sensors if sensor.name == "power")
    battery.flex_model = {
        "consumption": {"sensor": power_sensor.id},
        "soc-min": "0 MWh",
        "soc-max": "5 MWh",
        "power-capacity": "2 MW",
    }
    automation = build_schedule_automation(
        building,
        name="Schedule following the asset",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H"},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    run_automation(automation)
    generator_before = automation.generator
    assert "2 MW" in str(
        generator_before.attributes["data_generator"]["config"]["flex-model"]
    )

    # The site can now draw less power, which is a different configuration to schedule under.
    battery.flex_model = {**battery.flex_model, "power-capacity": "1 MW"}
    fresh_db.session.commit()

    run_automation(automation)
    generator_after = automation.generator
    assert generator_after.id != generator_before.id
    assert "1 MW" in str(
        generator_after.attributes["data_generator"]["config"]["flex-model"]
    )
    # Both describe the same scheduler, so only the configuration tells them apart.
    assert generator_after.model == generator_before.model
    assert generator_after.version == generator_before.version


def test_minimal_schedule_automation_reports_stored_flex_sensors(
    fresh_db, add_battery_assets_fresh_db
):
    battery = add_battery_assets_fresh_db["Test battery"]
    building = battery.parent_asset
    power_sensor = next(sensor for sensor in battery.sensors if sensor.name == "power")
    price_sensor = fresh_db.session.get(
        Sensor, battery.flex_context["consumption-price"]["sensor"]
    )
    building.flex_context = {
        **building.flex_context,
        "consumption-price": {"sensor": price_sensor.id},
    }
    battery.flex_model = {
        "consumption": {"sensor": power_sensor.id},
        "soc-at-start": "2.5 MWh",
        "soc-min": "0 MWh",
        "soc-max": "5 MWh",
        "power-capacity": "2 MW",
    }
    automation = build_schedule_automation(
        building,
        name="Minimal stored-flex sensor details",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H"},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    sensors = resolve_automation_sensors(automation)

    assert sensors["output_sensors"] == [power_sensor]
    assert price_sensor in sensors["input_sensors"]
    assert get_automations_feeding_sensor(power_sensor) == [automation]


def test_schedule_automation_stats_include_descendant_jobs_once(
    fresh_db, app, automation_with_generator, clean_scheduling_redis
):
    forecast_automation, _ = automation_with_generator
    root = forecast_automation.asset
    child = GenericAsset(
        name="automation child",
        generic_asset_type=root.generic_asset_type,
        parent_asset=root,
    )
    child_sensor = Sensor(
        name="child power",
        generic_asset=child,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    schedule_automation = build_schedule_automation(
        root,
        name="descendant schedules",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H"},
    )
    fresh_db.session.add_all([child_sensor, schedule_automation])
    fresh_db.session.flush()

    queue = app.queues["scheduling"]
    job = Job.create(
        "flexmeasures.utils.time_utils.server_now", connection=queue.connection
    )
    job.meta["trigger"] = {
        "origin": "automation",
        "automation_id": schedule_automation.id,
    }
    job.save_meta()
    queue.enqueue_job(job)
    app.job_cache.add(root.id, job.id, "scheduling", "asset")
    app.job_cache.add(child_sensor.id, job.id, "scheduling", "sensor")

    other_job = Job.create(
        "flexmeasures.utils.time_utils.server_now", connection=queue.connection
    )
    other_job.meta["trigger"] = {
        "origin": "automation",
        "automation_id": schedule_automation.id + 1,
    }
    other_job.save_meta()
    queue.enqueue_job(other_job)
    app.job_cache.add(child_sensor.id, other_job.id, "scheduling", "sensor")

    assert get_automation_job_stats(schedule_automation) == {"queued": 1}


def test_automation_has_valid_timezone_and_aware_cursor(automation_with_generator):
    automation, _ = automation_with_generator

    assert automation.timezone == "Asia/Seoul"
    assert automation.cursor.tzinfo is not None
    assert automation.cursor.utcoffset() == timezone.utc.utcoffset(None)


def test_automation_rejects_invalid_timezone(automation_with_generator):
    automation, _ = automation_with_generator

    with pytest.raises(ValueError, match="does not exist"):
        automation.timezone = "Europe/NotAmsterdam"


def test_a_scheduler_that_cannot_work_out_its_config_says_the_sensors_are_unknown(
    fresh_db, app, add_battery_assets_fresh_db, add_market_prices_fresh_db, mocker
):
    """A failure while collecting the flex config is reported as unknown sensors, not raised raw.

    Callers handle `AutomationSensorsUnknown`,
    so letting a scheduler's own `ValueError` through would reach the API as an unexpected failure instead.
    A `ValidationError` is deliberately not wrapped: it says the parameters are wrong, which the caller reports as such.
    """
    from marshmallow import ValidationError

    from flexmeasures.data.services.automations import (
        AutomationSensorsUnknown,
        resolve_schedule_automation_sensors,
    )

    battery = add_battery_assets_fresh_db["Test battery"]
    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = battery.sensors[0].id
    parameters = {**message, "flex-model": [flex_model]}

    mocker.patch(
        "flexmeasures.data.models.planning.Scheduler.collect_flex_config",
        side_effect=ValueError("no flex config to be had"),
    )
    with pytest.raises(AutomationSensorsUnknown, match="no flex config to be had"):
        resolve_schedule_automation_sensors(parameters, battery.id)

    # Parameters that do not form a schedule trigger at all stay a ValidationError.
    with pytest.raises(ValidationError):
        resolve_schedule_automation_sensors({"duration": "not a duration"}, battery.id)


def test_an_automations_schedule_refuses_a_sensor_nobody_checked(
    fresh_db, app, add_battery_assets_fresh_db, add_market_prices_fresh_db, mocker
):
    """A scheduler returning results for an undeclared sensor is refused, rather than recording on it.

    An automation's output sensors are checked against its creator's permissions when it is created,
    and those are predicted from the fields that name them.
    A sensor the prediction misses is read as an input instead,
    so it is checked for read access where recording data calls for create-children access.
    """
    import pandas as pd

    from flexmeasures.data.models.planning.storage import StorageScheduler
    from flexmeasures.data.services.scheduling import (
        ScheduleWritesUncheckedSensor,
        make_schedule,
    )

    battery = add_battery_assets_fresh_db["Test battery"]
    scheduled_sensor = battery.sensors[0]
    # A sensor of another asset, which the automation never declared and nobody was checked against.
    other_sensor = add_battery_assets_fresh_db["Test small battery"].sensors[0]

    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = scheduled_sensor.id
    automation = build_schedule_automation(
        battery,
        name="Nightly schedules",
        cronstr="0 0 * * *",
        parameters={**message, "flex-model": [flex_model]},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    job = mocker.Mock()
    job.meta = {"trigger": {"origin": "automation", "automation_id": automation.id}}
    mocker.patch(
        "flexmeasures.data.services.scheduling.get_current_job", return_value=job
    )
    mocker.patch.object(
        StorageScheduler,
        "compute",
        return_value=[
            {
                "name": "unchecked_schedule",
                "sensor": other_sensor,
                "data": pd.Series(
                    [1.0],
                    index=pd.date_range(
                        "2015-01-01T00:00:00+01:00", periods=1, freq="15min"
                    ),
                ),
            }
        ],
    )

    with pytest.raises(ScheduleWritesUncheckedSensor, match=str(other_sensor.id)):
        make_schedule(
            asset_or_sensor={"class": "Asset", "id": battery.id},
            start=pd.Timestamp("2015-01-01T00:00:00+01:00").to_pydatetime(),
            end=pd.Timestamp("2015-01-02T00:00:00+01:00").to_pydatetime(),
            resolution=timedelta(minutes=15),
            flex_model=[flex_model],
            flex_context={},
        )


def test_a_job_that_is_not_an_automations_is_held_to_nothing(app, fresh_db, mocker):
    """Only an automation's jobs are held to a declared set; everything else keeps its existing freedom.

    A schedule triggered through the API or the CLI has its sensors checked against the requester
    at trigger time, so there is nothing for this guard to add there.
    """
    from flexmeasures.data.services.scheduling import _sensors_this_job_may_record_on

    assert _sensors_this_job_may_record_on(None) is None

    api_job = mocker.Mock()
    api_job.meta = {"trigger": {"origin": "API"}}
    assert _sensors_this_job_may_record_on(api_job) is None

    # An automation deleted since its job was queued leaves nothing to hold the job to.
    gone = mocker.Mock()
    gone.meta = {"trigger": {"origin": "automation", "automation_id": 999999}}
    assert _sensors_this_job_may_record_on(gone) is None


def test_an_automation_whose_sensors_are_unknown_records_nothing(
    fresh_db, app, add_battery_assets_fresh_db, add_market_prices_fresh_db, mocker
):
    """A guard that cannot work out what is permitted permits nothing, rather than everything.

    The alternative, proceeding unchecked, is what the run-time check exists to stop.
    """
    from flexmeasures.data.services.automations import AutomationSensorsUnknown
    from flexmeasures.data.services.scheduling import _sensors_this_job_may_record_on

    battery = add_battery_assets_fresh_db["Test battery"]
    message = message_for_trigger_schedule()
    flex_model = message.pop("flex-model")
    flex_model["sensor"] = battery.sensors[0].id
    automation = build_schedule_automation(
        battery,
        name="Unknowable sensors",
        cronstr="0 0 * * *",
        parameters={**message, "flex-model": [flex_model]},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    mocker.patch(
        "flexmeasures.data.services.automations.resolve_automation_sensors",
        side_effect=AutomationSensorsUnknown("cannot tell"),
    )
    job = mocker.Mock()
    job.meta = {"trigger": {"origin": "automation", "automation_id": automation.id}}

    assert _sensors_this_job_may_record_on(job) == set()
