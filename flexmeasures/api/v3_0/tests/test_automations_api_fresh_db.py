"""Permission regressions for automation API details."""

from datetime import timedelta

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.automations import resolve_schedule_generator
from flexmeasures import Forecaster
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.data_sources import get_data_generator


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_details_reject_inaccessible_sensor_metadata(
    client,
    fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    prosumer_asset = setup_generic_assets_fresh_db["test_battery"]
    supplier_asset = setup_generic_assets_fresh_db["test_wind_turbine"]
    output_sensor = Sensor(
        name="prosumer output",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=prosumer_asset,
    )
    hidden_sensor = Sensor(
        name="private supplier regressor",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=supplier_asset,
    )
    fresh_db.session.add_all([output_sensor, hidden_sensor])
    fresh_db.session.flush()
    forecaster = get_data_generator(
        source=None,
        model="TrainPredictPipeline",
        config={"regressors": [hidden_sensor.id]},
        save_config=True,
        data_generator_type=Forecaster,
    )
    assert forecaster is not None
    generator = forecaster.data_source
    automation = Automation(
        asset=prosumer_asset,
        generator=generator,
        type="forecasting",
        name="Cross-organisation details",
        cronstr="0 6 * * *",
        parameters={"sensor": output_sensor.id},
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    response = client.get(
        url_for(
            "AssetAPI:get_automation",
            id=prosumer_asset.id,
            automation_id=automation.id,
        )
    )

    assert response.status_code == 403
    assert hidden_sensor.name not in response.text


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_schedule_details_include_stored_flex_sensors(
    client,
    fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    asset = setup_generic_assets_fresh_db["test_battery"]
    power_sensor = Sensor(
        name="scheduled power",
        unit="MW",
        event_resolution=timedelta(minutes=15),
        generic_asset=asset,
    )
    price_sensor = Sensor(
        name="schedule price",
        unit="EUR/MWh",
        event_resolution=timedelta(hours=1),
        generic_asset=asset,
    )
    fresh_db.session.add_all([power_sensor, price_sensor])
    fresh_db.session.flush()
    asset.flex_model = {
        "consumption": {"sensor": power_sensor.id},
        "soc-at-start": "2.5 MWh",
        "soc-min": "0 MWh",
        "soc-max": "5 MWh",
        "power-capacity": "2 MW",
    }
    asset.flex_context = {
        "site-power-capacity": "2 MVA",
        "consumption-price": {"sensor": price_sensor.id},
    }
    parameters = {"duration": "PT1H"}
    automation = Automation(
        asset=asset,
        type="scheduling",
        name="Minimal schedule details",
        cronstr="0 6 * * *",
        parameters=parameters,
        generator_id=resolve_schedule_generator(asset.id, parameters).id,
    )
    fresh_db.session.add(automation)
    fresh_db.session.commit()

    response = client.get(
        url_for(
            "AssetAPI:get_automation",
            id=asset.id,
            automation_id=automation.id,
        )
    )

    assert response.status_code == 200
    assert response.json["input-sensors"] == [
        {"id": price_sensor.id, "name": price_sensor.name}
    ]
    assert response.json["output-sensors"] == [
        {"id": power_sensor.id, "name": power_sensor.name}
    ]


@pytest.fixture(scope="function")
def add_automation_on_a_child_asset(fresh_db, add_battery_assets_fresh_db):
    """Put an automation on a sub-asset of the battery, where automations usually live."""
    battery = add_battery_assets_fresh_db["Test battery"]
    child = GenericAsset(
        name="Battery inverter",
        generic_asset_type=battery.generic_asset_type,
        parent_asset_id=battery.id,
        account_id=battery.account_id,
    )
    fresh_db.session.add(child)
    fresh_db.session.flush()
    automation = Automation(
        asset_id=child.id,
        generator=DataSource(
            name="child asset generator",
            type="forecaster",
            model="TrainPredictPipeline",
        ),
        type="forecasting",
        name="Inverter forecasts",
        cronstr="0 7 * * *",
        timezone="Europe/Amsterdam",
        active=True,
        parameters={"sensor": battery.sensors[0].id},
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()
    return child, automation


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations_includes_those_of_child_assets(
    app,
    add_battery_assets_fresh_db,
    add_automations_fresh_db,
    add_automation_on_a_child_asset,
    requesting_user,
):
    """An asset reports what runs below it, so that a site asset does not look idle."""
    battery = add_battery_assets_fresh_db["Test battery"]
    child, child_automation = add_automation_on_a_child_asset
    with app.test_client() as client:
        response = client.get(url_for("AssetAPI:get_automations", id=battery.id))
    assert response.status_code == 200
    automations = response.json["automations"]
    inverter = next(a for a in automations if a["id"] == child_automation.id)
    assert inverter["asset"] == child.id
    # Each entry names its asset, so that a listing spanning several of them stays readable.
    assert inverter["asset-name"] == "Battery inverter"
    assert {a["asset-name"] for a in automations} == {
        "Test battery",
        "Battery inverter",
    }


@pytest.fixture(scope="function")
def add_automation_on_a_foreign_child_asset(
    fresh_db, add_battery_assets_fresh_db, add_automation_on_a_child_asset
):
    """Put an automation on a sub-asset of the battery which belongs to another organisation than the battery does."""
    from flexmeasures.data.models.user import Account

    battery = add_battery_assets_fresh_db["Test battery"]
    other_account = Account(name="Another organisation")
    fresh_db.session.add(other_account)
    fresh_db.session.flush()
    foreign_child = GenericAsset(
        name="Leased inverter",
        generic_asset_type=battery.generic_asset_type,
        parent_asset_id=battery.id,
        account_id=other_account.id,
    )
    fresh_db.session.add(foreign_child)
    fresh_db.session.flush()
    foreign_automation = Automation(
        asset_id=foreign_child.id,
        generator=DataSource(
            name="foreign child asset generator",
            type="forecaster",
            model="TrainPredictPipeline",
        ),
        type="forecasting",
        name="Leased inverter forecasts",
        cronstr="0 8 * * *",
        timezone="Europe/Amsterdam",
        active=True,
        parameters={"sensor": battery.sensors[0].id},
    )
    fresh_db.session.add(foreign_automation)
    fresh_db.session.flush()
    return foreign_child, foreign_automation


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations_leaves_out_child_assets_the_user_may_not_read(
    app,
    add_battery_assets_fresh_db,
    add_automation_on_a_child_asset,
    add_automation_on_a_foreign_child_asset,
    requesting_user,
):
    """Being below an asset the user may read grants nothing, as a child asset can belong to another organisation."""
    battery = add_battery_assets_fresh_db["Test battery"]
    _, own_child_automation = add_automation_on_a_child_asset
    _, foreign_automation = add_automation_on_a_foreign_child_asset
    with app.test_client() as client:
        response = client.get(url_for("AssetAPI:get_automations", id=battery.id))
    assert response.status_code == 200
    listed_ids = [a["id"] for a in response.json["automations"]]
    assert own_child_automation.id in listed_ids
    assert foreign_automation.id not in listed_ids


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_jobs_leaves_out_child_assets_the_user_may_not_read(
    app,
    add_battery_assets_fresh_db,
    add_automation_on_a_child_asset,
    add_automation_on_a_foreign_child_asset,
    clean_redis,
    requesting_user,
):
    """The jobs of a sub-asset of another organisation stay out of the asset's jobs listing, too."""
    battery = add_battery_assets_fresh_db["Test battery"]
    own_child, _ = add_automation_on_a_child_asset
    foreign_child, _ = add_automation_on_a_foreign_child_asset
    job_ids = {}
    for child in (own_child, foreign_child):
        job = app.queues["scheduling"].enqueue(sum, [1, 2])
        app.job_map.add(
            child.id, job.id, queue="scheduling", asset_or_sensor_type="asset"
        )
        job_ids[child.id] = job.id
    with app.test_client() as client:
        response = client.get(url_for("AssetAPI:get_jobs", id=battery.id))
    assert response.status_code == 200
    listed_ids = [job["job_id"] for job in response.json["jobs"]]
    assert job_ids[own_child.id] in listed_ids
    assert job_ids[foreign_child.id] not in listed_ids
    app.queues["scheduling"].empty()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations_can_be_narrowed_to_the_asset_itself(
    app,
    add_battery_assets_fresh_db,
    add_automations_fresh_db,
    add_automation_on_a_child_asset,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    _, child_automation = add_automation_on_a_child_asset
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
            query_string={"include-child-assets": "false"},
        )
    assert response.status_code == 200
    automations = response.json["automations"]
    assert child_automation.id not in [a["id"] for a in automations]
    assert {a["asset-name"] for a in automations} == {"Test battery"}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_reusing_a_data_source(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
):
    """Naming an existing data source reuses the data generator and the configuration stored on it."""
    battery = add_battery_assets_fresh_db["Test battery"]
    sensor_id = battery.sensors[0].id
    with app.test_client() as client:
        first_response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts defining a generator",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": sensor_id},
            },
        )
        assert first_response.status_code == 201, first_response.json
        source_id = fresh_db.session.get(
            Automation, first_response.json["id"]
        ).generator_id

        second_response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts reusing that generator",
                "cron": "0 18 * * *",
                "type": "forecasting",
                "source": source_id,
                "parameters": {"sensor": sensor_id},
            },
        )
    assert second_response.status_code == 201, second_response.json
    reusing_automation = fresh_db.session.get(Automation, second_response.json["id"])
    assert reusing_automation.generator_id == source_id


@pytest.mark.parametrize(
    "extra_fields, expected_message",
    [
        (
            {"data-generator": "TrainPredictPipeline"},
            "data-generator cannot be combined with source",
        ),
        ({"config": {"model": "CustomLGBM"}}, "config cannot be combined with source"),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_refuses_a_source_beside_a_generator(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
    extra_fields,
    expected_message,
):
    """A data source already stores the data generator and its config, so naming both ways at once is refused."""
    battery = add_battery_assets_fresh_db["Test battery"]
    source = DataSource(
        name="reusable forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {}}},
    )
    fresh_db.session.add(source)
    fresh_db.session.flush()
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Over-specified forecasts",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "source": source.id,
                "parameters": {"sensor": battery.sensors[0].id},
                **extra_fields,
            },
        )
    assert response.status_code == 422
    assert expected_message in str(response.json)
    assert (
        fresh_db.session.execute(
            select(Automation).filter_by(name="Over-specified forecasts")
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_schedule_automation_refuses_a_source(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
):
    """A schedule automation resolves its data source on every run, so it cannot be pinned to one."""
    battery = add_battery_assets_fresh_db["Test battery"]
    source = DataSource(
        name="reusable forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {}}},
    )
    fresh_db.session.add(source)
    fresh_db.session.flush()
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Pinned schedules",
                "cron": "0 0 * * *",
                "type": "scheduling",
                "source": source.id,
                "parameters": {"duration": "PT12H"},
            },
        )
    assert response.status_code == 422
    assert "schedule automation cannot name a source" in str(response.json)


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_with_a_source_of_another_account(
    app,
    fresh_db,
    setup_accounts_fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
):
    """A data source the caller cannot read is not theirs to compute under, whatever it stores."""
    battery = add_battery_assets_fresh_db["Test battery"]
    foreign_source = DataSource(
        name="foreign forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {}}},
        account=setup_accounts_fresh_db["Dummy"],
    )
    fresh_db.session.add(foreign_source)
    fresh_db.session.flush()
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Borrowed forecasts",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "source": foreign_source.id,
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
    assert response.status_code == 403
    assert (
        fresh_db.session.execute(
            select(Automation).filter_by(name="Borrowed forecasts")
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_accepts_an_empty_source(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
):
    """Leaving the source field empty means the automation sets up its own data generator, as leaving it out does."""
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts without a source",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "source": None,
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
    assert response.status_code == 201, response.json
    automation = fresh_db.session.execute(
        select(Automation).filter_by(name="Forecasts without a source")
    ).scalar_one()
    assert automation.generator_id is not None


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_automation_refuses_a_source_one_may_only_read(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    """Having seen what a source computed on one's own sensor does not make it a source to record under."""
    from flexmeasures.data.models.data_sources import SensorDataSource

    battery = add_battery_assets_fresh_db["Test battery"]
    sensor = battery.sensors[0]
    foreign_source = DataSource(
        name="foreign forecaster",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={"data_generator": {"config": {}}},
        account=setup_accounts_fresh_db["Dummy"],
    )
    fresh_db.session.add(foreign_source)
    fresh_db.session.flush()
    # The source has recorded on a sensor of the user's own asset, which makes it readable, but not theirs to work with.
    fresh_db.session.add(
        SensorDataSource(sensor_id=sensor.id, source_id=foreign_source.id)
    )
    fresh_db.session.flush()

    with app.test_client() as client:
        readable = client.get(url_for("SourceAPI:get", id=foreign_source.id))
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts under a source only seen",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "source": foreign_source.id,
                "parameters": {"sensor": sensor.id},
            },
        )
    assert readable.status_code == 200
    assert response.status_code == 403
    assert "not yours to work with" in str(response.json)
    assert (
        fresh_db.session.execute(
            select(Automation).filter_by(name="Forecasts under a source only seen")
        ).scalar_one_or_none()
        is None
    )
