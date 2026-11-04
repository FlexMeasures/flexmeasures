"""Tests for POST /api/v3_0/assets/<id>/reports/trigger where the request is refused or only queues a job."""

import pytest
from flask import url_for
from sqlalchemy import func, select

from flexmeasures.api.v3_0.tests.utils import report_message
from flexmeasures.data.models.data_sources import DataSource

# Tests here share one database, so the rows each test adds are deleted afterwards.
pytestmark = pytest.mark.usefixtures("undo_new_rows")


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
@pytest.mark.parametrize("reporter", ["AggregatorReporter", "ProfitOrLossReporter"])
def test_trigger_report_rejects_missing_specialized_dataflow_fields_without_side_effects(
    app,
    db,
    setup_report_sensors,
    clean_redis,
    requesting_user,
    reporter,
):
    sensors = setup_report_sensors
    if reporter == "AggregatorReporter":
        missing_field = "output"
        message = {
            "reporter": reporter,
            "config": {"method": "sum"},
            "parameters": {
                "input": [{"sensor": sensors["input_1"].id}],
                "start": "2023-04-10T00:00:00+00:00",
                "end": "2023-04-10T10:00:00+00:00",
            },
        }
    else:
        missing_field = "input"
        message = {
            "reporter": reporter,
            "config": {"consumption_price_sensor": sensors["local_price"].id},
            "parameters": {
                "output": [{"sensor": sensors["cost_output"].id}],
                "start": "2023-04-10T00:00:00+00:00",
                "end": "2023-04-10T10:00:00+00:00",
            },
        }

    source_count = reporter_source_count(db)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )

    assert response.status_code == 422
    assert missing_field in str(response.json)
    assert reporter_source_count(db) == source_count
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("dependency", ["parameter", "config"])
def test_trigger_report_rejects_inaccessible_inputs_without_side_effects(
    app,
    db,
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
    source_count = reporter_source_count(db)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 403
    assert reporter_source_count(db) == source_count
    assert app.queues["reporting"].jobs == []


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_rejects_output_outside_asset_subtree(
    app, db, setup_report_sensors, clean_redis, requesting_user
):
    sensors = setup_report_sensors
    message = report_message(
        sensors["input_1"], sensors["input_2"], sensors["sibling_output"]
    )
    source_count = reporter_source_count(db)
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 422
    assert "must belong to asset" in str(response.json)
    assert reporter_source_count(db) == source_count
    assert app.queues["reporting"].jobs == []
