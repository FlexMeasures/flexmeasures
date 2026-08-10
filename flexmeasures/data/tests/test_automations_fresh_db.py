from __future__ import annotations

from datetime import timedelta, timezone

import pytest
from rq.job import Job
from sqlalchemy.exc import IntegrityError

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.automations import (
    get_automation_job_stats,
    run_automation,
)


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
        type="forecasts",
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


def test_schedule_automation_does_not_require_generator(
    fresh_db, automation_with_generator
):
    forecast_automation, _ = automation_with_generator
    schedule_automation = Automation(
        asset=forecast_automation.asset,
        type="schedules",
        name="generator-free schedule",
        cronstr="0 * * * *",
        parameters={"duration": "PT1H"},
    )
    fresh_db.session.add(schedule_automation)
    fresh_db.session.commit()

    assert schedule_automation.generator_id is None


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

    automation = Automation(
        asset_id=battery.id,
        type="schedules",
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
    automation = Automation(
        asset=building,
        type="schedules",
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
    schedule_automation = Automation(
        asset=root,
        type="schedules",
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
    assert automation.scheduling_cursor.tzinfo is not None
    assert automation.scheduling_cursor.utcoffset() == timezone.utc.utcoffset(None)


def test_automation_rejects_invalid_timezone(automation_with_generator):
    automation, _ = automation_with_generator

    with pytest.raises(ValueError, match="does not exist"):
        automation.timezone = "Europe/NotAmsterdam"
