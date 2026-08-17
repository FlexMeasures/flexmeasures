"""Tests for POST /api/v3_0/assets/<id>/reports/trigger."""

from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from sqlalchemy import func, select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.utils.job_utils import work_on_rq


@pytest.fixture
def setup_report_sensors(
    fresh_db,
    add_battery_assets_fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
):
    """Create report sensors inside and outside the target asset subtree."""
    battery = add_battery_assets_fresh_db["Test battery"]
    input_1 = Sensor(
        "report input 1",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    input_2 = Sensor(
        "report input 2",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    output = Sensor(
        "report output", generic_asset=battery, event_resolution=timedelta(hours=2)
    )
    cost_output = Sensor(
        "cost output",
        generic_asset=battery,
        event_resolution=timedelta(hours=2),
        unit="EUR",
    )
    sibling = GenericAsset(
        name="Sibling battery",
        generic_asset_type=setup_generic_asset_types_fresh_db["battery"],
        owner=setup_accounts_fresh_db["Prosumer"],
        parent_asset=battery.parent_asset,
    )
    sibling_output = Sensor(
        "sibling output", generic_asset=sibling, event_resolution=timedelta(hours=2)
    )
    foreign = GenericAsset(
        name="Foreign report asset",
        generic_asset_type=setup_generic_asset_types_fresh_db["battery"],
        owner=setup_accounts_fresh_db["Dummy"],
    )
    foreign_input = Sensor(
        "foreign input",
        generic_asset=foreign,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    foreign_price = Sensor(
        "foreign price",
        generic_asset=foreign,
        event_resolution=timedelta(hours=1),
        unit="EUR/kWh",
    )
    fresh_db.session.add_all(
        [
            input_1,
            input_2,
            output,
            cost_output,
            sibling,
            sibling_output,
            foreign,
            foreign_input,
            foreign_price,
        ]
    )
    fresh_db.session.flush()
    return {
        "asset": battery,
        "input_1": input_1,
        "input_2": input_2,
        "output": output,
        "cost_output": cost_output,
        "sibling_output": sibling_output,
        "foreign_input": foreign_input,
        "foreign_price": foreign_price,
    }


def report_message(sensor_1: Sensor, sensor_2: Sensor, output: Sensor) -> dict:
    return {
        "reporter": "PandasReporter",
        "config": {
            "required_input": [{"name": "one"}, {"name": "two"}],
            "required_output": [{"name": "sum"}],
            "transformations": [
                {
                    "df_input": "one",
                    "method": "add",
                    "args": ["@two"],
                    "df_output": "sum",
                },
                {"method": "resample_events", "args": ["2h"]},
            ],
        },
        "parameters": {
            "input": [
                {"name": "one", "sensor": sensor_1.id},
                {"name": "two", "sensor": sensor_2.id},
            ],
            "output": [{"name": "sum", "sensor": output.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        },
    }


def reporter_source_count(db) -> int:
    return db.session.scalar(
        select(func.count())
        .select_from(DataSource)
        .where(DataSource.type == "reporter")
    )


@pytest.mark.parametrize(
    "requesting_user, expected_status",
    [
        (None, 401),
        ("test_prosumer_user@seita.nl", 202),
        ("test_dummy_user_3@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_trigger_report_auth(
    app, setup_report_sensors, clean_redis, requesting_user, expected_status
):
    sensors = setup_report_sensors
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id),
            json=report_message(
                sensors["input_1"], sensors["input_2"], sensors["output"]
            ),
        )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_queues_canonical_job_response(
    app, setup_report_sensors, clean_redis, requesting_user
):
    sensors = setup_report_sensors
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id),
            json=report_message(
                sensors["input_1"], sensors["input_2"], sensors["output"]
            ),
        )

    assert response.status_code == 202
    assert response.json["status"] == "ACCEPTED"
    job = app.queues["reporting"].jobs[0]
    assert response.json["job"] == job.id
    assert response.json["job-url"].endswith(f"/jobs/{job.id}")
    assert job.meta["trigger"] == {"origin": "API"}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_worker_stores_report_data(
    app, fresh_db, setup_report_sensors, clean_redis, requesting_user
):
    """Exercise the API, reporting queue, worker function and persisted output."""
    sensors = setup_report_sensors
    source = DataSource("report input source")
    fresh_db.session.add(source)
    fresh_db.session.flush()
    with fresh_db.session.no_autoflush:
        beliefs = [
            TimedBelief(
                event_start=datetime(2023, 4, 10, hour=hour, tzinfo=timezone.utc),
                belief_time=datetime(2023, 4, 9, tzinfo=timezone.utc),
                event_value=hour,
                sensor=sensor,
                source=source,
            )
            for sensor in (sensors["input_1"], sensors["input_2"])
            for hour in range(10)
        ]
    fresh_db.session.add_all(beliefs)
    fresh_db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id),
            json=report_message(
                sensors["input_1"], sensors["input_2"], sensors["output"]
            ),
        )
    assert response.status_code == 202

    work_on_rq(app.queues["reporting"])
    stored_report = sensors["output"].search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-10T10:00:00+00:00",
    )
    assert stored_report.values.T.tolist() == [[1, 5, 9, 13, 17]]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "mutation, expected_text",
    [
        (lambda message: message["parameters"].pop("start"), "start"),
        (lambda message: message["parameters"].pop("output"), "output"),
        (lambda message: message.update(reporter="UnknownReporter"), "UnknownReporter"),
        (lambda message: message["config"].update(invalid=1), "invalid"),
    ],
)
def test_trigger_report_rejects_invalid_requests(
    app,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    mutation,
    expected_text,
):
    sensors = setup_report_sensors
    message = report_message(sensors["input_1"], sensors["input_2"], sensors["output"])
    mutation(message)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 422
    assert expected_text.casefold() in str(response.json).casefold()
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("dependency", ["parameter", "config"])
def test_trigger_report_rejects_inaccessible_inputs_without_side_effects(
    app,
    fresh_db,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    dependency,
):
    sensors = setup_report_sensors
    if dependency == "parameter":
        message = report_message(
            sensors["foreign_input"], sensors["input_2"], sensors["output"]
        )
    else:
        message = {
            "reporter": "ProfitOrLossReporter",
            "config": {"consumption_price_sensor": sensors["foreign_price"].id},
            "parameters": {
                "input": [{"sensor": sensors["input_1"].id}],
                "output": [{"sensor": sensors["cost_output"].id}],
                "start": "2023-04-10T00:00:00+00:00",
                "end": "2023-04-10T10:00:00+00:00",
            },
        }
    source_count = reporter_source_count(fresh_db)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 403
    assert reporter_source_count(fresh_db) == source_count
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_rejects_output_outside_asset_subtree(
    app, fresh_db, setup_report_sensors, clean_redis, requesting_user
):
    sensors = setup_report_sensors
    message = report_message(
        sensors["input_1"], sensors["input_2"], sensors["sibling_output"]
    )
    source_count = reporter_source_count(fresh_db)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 422
    assert "must belong to asset" in str(response.json)
    assert reporter_source_count(fresh_db) == source_count
    assert app.queues["reporting"].jobs == []
