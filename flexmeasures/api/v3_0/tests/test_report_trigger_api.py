"""Tests for the report trigger endpoint (POST /api/v3_0/assets/<id>/reports/trigger)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for
from sqlalchemy import func, select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture
def setup_report_sensors(
    fresh_db,
    add_battery_assets_fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
):
    """Add report sensors in the target, a sibling and another organisation."""
    battery = add_battery_assets_fresh_db["Test battery"]
    sensor_1 = Sensor(
        "input sensor 1",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    sensor_2 = Sensor(
        "input sensor 2",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    report_sensor = Sensor(
        "report sensor", generic_asset=battery, event_resolution=timedelta(hours=2)
    )
    cost_output = Sensor(
        "cost report sensor",
        generic_asset=battery,
        event_resolution=timedelta(hours=2),
        unit="EUR",
    )

    sibling_asset = GenericAsset(
        name="Sibling battery",
        generic_asset_type=setup_generic_asset_types_fresh_db["battery"],
        owner=setup_accounts_fresh_db["Prosumer"],
        parent_asset=battery.parent_asset,
    )
    sibling_output = Sensor(
        "sibling report sensor",
        generic_asset=sibling_asset,
        event_resolution=timedelta(hours=2),
    )

    foreign_asset = GenericAsset(
        name="Foreign report asset",
        generic_asset_type=setup_generic_asset_types_fresh_db["battery"],
        owner=setup_accounts_fresh_db["Dummy"],
    )
    foreign_input = Sensor(
        "foreign input sensor",
        generic_asset=foreign_asset,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    foreign_price = Sensor(
        "foreign price sensor",
        generic_asset=foreign_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/kWh",
    )

    fresh_db.session.add_all(
        [
            sensor_1,
            sensor_2,
            report_sensor,
            cost_output,
            sibling_asset,
            sibling_output,
            foreign_asset,
            foreign_input,
            foreign_price,
        ]
    )
    fresh_db.session.flush()
    return {
        "asset": battery,
        "input_1": sensor_1,
        "input_2": sensor_2,
        "output": report_sensor,
        "cost_output": cost_output,
        "sibling_output": sibling_output,
        "foreign_input": foreign_input,
        "foreign_price": foreign_price,
    }


def make_report_trigger_message(
    sensor_1: Sensor, sensor_2: Sensor, report_sensor: Sensor
) -> dict:
    """A PandasReporter message that adds up two sensors at a two-hour resolution."""
    return {
        "reporter": "PandasReporter",
        "config": {
            "required_input": [{"name": "sensor_1"}, {"name": "sensor_2"}],
            "required_output": [{"name": "df_agg"}],
            "transformations": [
                {
                    "df_input": "sensor_1",
                    "method": "add",
                    "args": ["@sensor_2"],
                    "df_output": "df_agg",
                },
                {"method": "resample_events", "args": ["2h"]},
            ],
        },
        "parameters": {
            "input": [
                {"name": "sensor_1", "sensor": sensor_1.id},
                {"name": "sensor_2", "sensor": sensor_2.id},
            ],
            "output": [{"name": "df_agg", "sensor": report_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        },
    }


def make_profit_trigger_message(
    input_sensor: Sensor, output_sensor: Sensor, price_sensor: Sensor
) -> dict:
    """A profit report whose price dependency is part of the reporter config."""
    return {
        "reporter": "ProfitOrLossReporter",
        "config": {"consumption_price_sensor": price_sensor.id},
        "parameters": {
            "input": [{"sensor": input_sensor.id}],
            "output": [{"sensor": output_sensor.id}],
            "start": "2023-04-10T00:00:00+00:00",
            "end": "2023-04-10T10:00:00+00:00",
        },
    }


def count_reporter_sources(db) -> int:
    """Count persisted reporter data sources."""
    return db.session.scalar(
        select(func.count())
        .select_from(DataSource)
        .where(DataSource.type == "reporter")
    )


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),
        ("test_prosumer_user@seita.nl", 202),
        ("test_dummy_user_3@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_trigger_report_auth(
    app,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    expected_status_code,
):
    """Triggering a report requires create-children access to the asset."""
    message = make_report_trigger_message(
        setup_report_sensors["input_1"],
        setup_report_sensors["input_2"],
        setup_report_sensors["output"],
    )
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=setup_report_sensors["asset"].id),
            json=message,
        )
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report(
    app,
    setup_report_sensors,
    clean_redis,
    requesting_user,
):
    """A successful trigger queues a reporting job with API provenance."""
    message = make_report_trigger_message(
        setup_report_sensors["input_1"],
        setup_report_sensors["input_2"],
        setup_report_sensors["output"],
    )
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=setup_report_sensors["asset"].id),
            json=message,
        )
    assert response.status_code == 202
    assert response.json["status"] == "ACCEPTED"
    job_id = response.json["job"]
    assert response.json["job-url"].endswith(f"/jobs/{job_id}")

    jobs = app.queues["reporting"].jobs
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == job_id
    assert job.meta["trigger"] == {"origin": "API"}
    assert job.kwargs["parameters"]["output"] == message["parameters"]["output"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "message_updates, expected_error_field",
    [
        ({"parameters": {"start": None, "end": None}}, "start"),
        ({"parameters": {"output": None}}, "output"),
        ({"reporter": "UnknownReporter"}, "UnknownReporter"),
        ({"config": {"invalid_field": 1}}, "invalid_field"),
        ({"reporter": None, "parameters": None}, "reporter"),
    ],
)
def test_trigger_report_with_invalid_message(
    app,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    message_updates,
    expected_error_field,
):
    """Invalid trigger messages yield a 422 without queueing a job."""
    message = make_report_trigger_message(
        setup_report_sensors["input_1"],
        setup_report_sensors["input_2"],
        setup_report_sensors["output"],
    )

    for field, update in message_updates.items():
        if update is None:
            del message[field]
        elif isinstance(update, dict):
            for subfield, subupdate in update.items():
                if subupdate is None:
                    del message[field][subfield]
                else:
                    message[field][subfield] = subupdate
        else:
            message[field] = update

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=setup_report_sensors["asset"].id),
            json=message,
        )
    assert response.status_code == 422
    assert expected_error_field.casefold() in str(response.json).casefold()
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "message_factory",
    [
        lambda sensors: make_report_trigger_message(
            sensors["foreign_input"], sensors["input_2"], sensors["output"]
        ),
        lambda sensors: make_profit_trigger_message(
            sensors["input_1"], sensors["cost_output"], sensors["foreign_price"]
        ),
    ],
    ids=["parameter-input", "reporter-config-price"],
)
def test_trigger_report_rejects_inaccessible_input_dependencies(
    app,
    fresh_db,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    message_factory,
):
    """All parameter and reporter-config input sensors require read access."""
    source_count = count_reporter_sources(fresh_db)
    message = message_factory(setup_report_sensors)

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=setup_report_sensors["asset"].id),
            json=message,
        )

    assert response.status_code == 403
    assert count_reporter_sources(fresh_db) == source_count
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_rejects_output_outside_asset_subtree(
    app,
    fresh_db,
    setup_report_sensors,
    clean_redis,
    requesting_user,
):
    """An accessible sibling sensor cannot be an output for the URL asset."""
    source_count = count_reporter_sources(fresh_db)
    message = make_report_trigger_message(
        setup_report_sensors["input_1"],
        setup_report_sensors["input_2"],
        setup_report_sensors["sibling_output"],
    )

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=setup_report_sensors["asset"].id),
            json=message,
        )

    assert response.status_code == 422
    assert "must belong to asset" in str(response.json)
    assert count_reporter_sources(fresh_db) == source_count
    assert app.queues["reporting"].jobs == []
