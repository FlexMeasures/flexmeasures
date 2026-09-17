"""Plugin automation validation, persistence, queueing and execution permissions."""

from datetime import timedelta

from flask import Flask
from flask_login import login_user, logout_user
from marshmallow import ValidationError
import pytest
from rq.job import Job
from werkzeug.exceptions import Forbidden

from flexmeasures.data.automations import (
    AutomationHandler,
    get_automation_handler,
    get_automation_types,
    register_automation_handler,
)
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.services.automations import (
    create_automation,
    resolve_automation_sensors,
    run_automation,
)
from flexmeasures.data.tests.plugins.mock_ingestion import (
    MockIngestionGenerator,
    __automation_types__,
)
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.utils.plugin_utils import register_plugins


@pytest.fixture
def ingestion_plugin(app, monkeypatch):
    monkeypatch.setattr(app, "automation_handlers", dict(app.automation_handlers))
    monkeypatch.setattr(
        app,
        "data_generators",
        {key: dict(value) for key, value in app.data_generators.items()},
    )
    register_automation_handler(app, __automation_types__[0])
    app.redis_connection.flushdb()
    yield
    app.redis_connection.flushdb()


@pytest.fixture
def ingestion_assets(fresh_db):
    account = Account(name="Ingestion organisation")
    other_account = Account(name="Other ingestion organisation")
    asset_type = GenericAssetType(name="Ingestion asset type")
    root = GenericAsset(
        name="Ingestion site", generic_asset_type=asset_type, owner=account
    )
    child = GenericAsset(
        name="Ingestion meter",
        generic_asset_type=asset_type,
        parent_asset=root,
        owner=account,
    )
    other = GenericAsset(
        name="Other site", generic_asset_type=asset_type, owner=other_account
    )
    sensors = [
        Sensor(
            name="measurement",
            generic_asset=asset,
            unit="kWh",
            event_resolution=timedelta(hours=1),
        )
        for asset in (root, child, other)
    ]
    fresh_db.session.add_all(sensors)
    fresh_db.session.commit()
    return root, sensors


def make_automation(fresh_db, asset, sensor, **kwargs):
    automation, warnings = create_automation(
        asset=asset,
        name="Read external measurements",
        cronstr="0 * * * *",
        automation_type="mock-ingestion",
        config={"sensor": sensor.id},
        **kwargs,
    )
    assert warnings == []
    fresh_db.session.add(automation)
    fresh_db.session.commit()
    return automation


def test_plugin_registration(app, ingestion_plugin):
    assert get_automation_types()["mock-ingestion"].display_name == "Mock ingestion"
    assert (
        get_automation_handler("mock-ingestion").generator_class
        is MockIngestionGenerator
    )
    assert (
        app.data_generators["ingestor"]["MockIngestionGenerator"]
        is MockIngestionGenerator
    )
    with pytest.raises(ValueError):
        register_automation_handler(app, __automation_types__[0])
    with pytest.raises(ValueError):
        register_automation_handler(
            app, AutomationHandler("forecasting", "Collision", MockIngestionGenerator)
        )


def test_plugin_loader_discovers_declared_automation(app):
    plugin_app = Flask("plugin-automation-test")
    plugin_app.config["FLEXMEASURES_PLUGINS"] = [
        "flexmeasures.data.tests.plugins.mock_ingestion"
    ]
    plugin_app.automation_handlers = {}
    plugin_app.data_generators = {"forecaster": {}, "reporter": {}, "scheduler": {}}
    plugin_app.queues = app.queues
    register_plugins(plugin_app)
    with plugin_app.app_context():
        assert get_automation_types()["mock-ingestion"].display_name == "Mock ingestion"
        assert (
            get_automation_handler("mock-ingestion").generator_class
            is MockIngestionGenerator
        )
    assert (
        "flexmeasures.data.tests.plugins.mock_ingestion"
        in plugin_app.config["LOADED_PLUGINS"]
    )


@pytest.mark.parametrize("field", ["config", "parameters"])
def test_plugin_rejects_unknown_fields(
    fresh_db, ingestion_plugin, ingestion_assets, field
):
    root, sensors = ingestion_assets
    kwargs = {"config": {"sensor": sensors[0].id}, "parameters": {}}
    kwargs[field]["unrecognized"] = True
    with pytest.raises(ValidationError):
        create_automation(
            root,
            "Invalid ingestion",
            "0 * * * *",
            automation_type="mock-ingestion",
            **kwargs,
        )


@pytest.mark.parametrize("sensor_index", [0, 1])
def test_plugin_queue_and_worker(
    fresh_db, app, ingestion_plugin, ingestion_assets, sensor_index
):
    root, sensors = ingestion_assets
    sensor = sensors[sensor_index]
    automation = make_automation(fresh_db, root, sensor, parameters={"value": 17.5})
    assert automation.generator.model == "MockIngestionGenerator"
    assert automation.generator.type == "ingestor"
    assert resolve_automation_sensors(automation) == {
        "input_sensors": [],
        "output_sensors": [sensor],
    }
    result = run_automation(automation)
    assert result["n_jobs"] == 1
    job = Job.fetch(result["job_id"], connection=app.redis_connection)
    assert job.origin == "ingestion"
    assert job.meta["trigger"] == {
        "origin": "automation",
        "automation_id": automation.id,
    }
    work_on_rq(app.queues["ingestion"], job=job)
    job.refresh()
    assert job.is_finished, job.exc_info
    beliefs = fresh_db.session.query(TimedBelief).filter_by(sensor_id=sensor.id).all()
    assert len(beliefs) == 1
    assert beliefs[0].event_value == 17.5
    assert beliefs[0].source_id == automation.generator_id


def test_plugin_rejects_outputs_outside_asset_tree(
    fresh_db, ingestion_plugin, ingestion_assets
):
    root, sensors = ingestion_assets
    with pytest.raises(ValueError, match="descendant|subtree|belong"):
        make_automation(fresh_db, root, sensors[2])


def test_missing_plugin_cannot_run(fresh_db, app, ingestion_plugin, ingestion_assets):
    root, sensors = ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0])
    del app.automation_handlers["mock-ingestion"]
    with pytest.raises(NotImplementedError, match="mock-ingestion"):
        run_automation(automation)


def test_cross_organisation_input_rejected(
    fresh_db, app, ingestion_plugin, ingestion_assets, setup_roles_users_fresh_db
):
    root, sensors = ingestion_assets
    user = fresh_db.session.get(User, setup_roles_users_fresh_db["Test Prosumer User"])
    root.owner = user.account
    sensors[0].generic_asset.owner = user.account
    fresh_db.session.commit()
    with app.test_request_context():
        login_user(user)
        try:
            with pytest.raises(Forbidden):
                create_automation(
                    root,
                    "Forbidden input",
                    "0 * * * *",
                    automation_type="mock-ingestion",
                    config={"sensor": sensors[0].id, "input-sensor": sensors[2].id},
                    check_permissions=True,
                )
        finally:
            logout_user()


@pytest.mark.parametrize("revocation", ["inactive", "organisation", "deleted"])
def test_plugin_execution_rechecks_creator_permissions(
    fresh_db,
    app,
    ingestion_plugin,
    ingestion_assets,
    setup_roles_users_fresh_db,
    revocation,
):
    root, sensors = ingestion_assets
    user = fresh_db.session.get(User, setup_roles_users_fresh_db["Test Prosumer User"])
    root.owner = user.account
    fresh_db.session.commit()
    with app.test_request_context():
        login_user(user)
        try:
            automation = make_automation(
                fresh_db, root, sensors[0], check_permissions=True
            )
        finally:
            logout_user()
    assert automation.execution_user_id == user.id
    if revocation == "inactive":
        user.active = False
    elif revocation == "deleted":
        fresh_db.session.delete(user)
    else:
        root.owner = sensors[2].generic_asset.owner
    fresh_db.session.commit()
    with pytest.raises(Forbidden):
        run_automation(automation)
    assert app.queues["ingestion"].count == 0


def test_worker_rechecks_permissions_after_queueing(
    fresh_db,
    app,
    ingestion_plugin,
    ingestion_assets,
    setup_roles_users_fresh_db,
):
    root, sensors = ingestion_assets
    user = fresh_db.session.get(User, setup_roles_users_fresh_db["Test Prosumer User"])
    root.owner = user.account
    fresh_db.session.commit()
    with app.test_request_context():
        login_user(user)
        try:
            automation = make_automation(
                fresh_db, root, sensors[0], check_permissions=True
            )
        finally:
            logout_user()
    result = run_automation(automation)
    user.active = False
    fresh_db.session.commit()
    job = Job.fetch(result["job_id"], connection=app.redis_connection)
    work_on_rq(app.queues["ingestion"], job=job)
    job.refresh()
    assert job.is_failed
    assert fresh_db.session.query(TimedBelief).count() == 0


def test_worker_rejects_undeclared_output(
    fresh_db, app, ingestion_plugin, ingestion_assets, monkeypatch
):
    root, sensors = ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0])
    original_compute = MockIngestionGenerator._compute

    def compute_with_undeclared_output(generator, value):
        result = original_compute(generator, value)
        result[0]["sensor"] = sensors[1]
        return result

    monkeypatch.setattr(
        MockIngestionGenerator, "_compute", compute_with_undeclared_output
    )
    result = run_automation(automation)
    job = Job.fetch(result["job_id"], connection=app.redis_connection)
    work_on_rq(app.queues["ingestion"], job=job)
    job.refresh()
    assert job.is_failed
    assert fresh_db.session.query(TimedBelief).count() == 0


@pytest.mark.parametrize("during_worker", [False, True])
def test_plugin_generator_version_must_match(
    fresh_db, app, ingestion_plugin, ingestion_assets, monkeypatch, during_worker
):
    root, sensors = ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0])
    result = run_automation(automation) if during_worker else None
    monkeypatch.setattr(MockIngestionGenerator, "__version__", "2.0")
    if during_worker:
        job = Job.fetch(result["job_id"], connection=app.redis_connection)
        work_on_rq(app.queues["ingestion"], job=job)
        job.refresh()
        assert job.is_failed
        assert "Recreate" in job.latest_result().exc_string
    else:
        with pytest.raises(ValueError, match="Recreate"):
            run_automation(automation)
    assert fresh_db.session.query(TimedBelief).count() == 0


def test_worker_requires_installed_plugin(
    fresh_db, app, ingestion_plugin, ingestion_assets
):
    root, sensors = ingestion_assets
    automation = make_automation(fresh_db, root, sensors[0])
    result = run_automation(automation)
    del app.automation_handlers["mock-ingestion"]
    job = Job.fetch(result["job_id"], connection=app.redis_connection)
    work_on_rq(app.queues["ingestion"], job=job)
    job.refresh()
    assert job.is_failed
    assert "Install or enable" in job.latest_result().exc_string
    assert fresh_db.session.query(TimedBelief).count() == 0
