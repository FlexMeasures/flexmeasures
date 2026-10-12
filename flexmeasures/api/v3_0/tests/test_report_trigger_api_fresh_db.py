"""Tests for POST /api/v3_0/assets/<id>/reports/trigger which run the worker, and so leave data behind on the input sensors."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from rq.job import JobStatus

from flexmeasures.api.v3_0.tests.utils import report_message
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.utils.job_utils import work_on_rq


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_worker_stores_report_data(
    app, fresh_db, setup_report_sensors_fresh_db, clean_redis, caplog, requesting_user
):
    """Exercise the API, reporting queue, worker function and persisted output."""
    sensors = setup_report_sensors_fresh_db
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

    with caplog.at_level(logging.INFO):
        work_on_rq(app.queues["reporting"])
    assert any(
        "ran successfully" in record.message
        and str(sensors["output"].id) in record.message
        for record in caplog.records
    )
    stored_report = sensors["output"].search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-10T10:00:00+00:00",
    )
    # Adding the two hourly 0-9 input series yields 0, 2, ..., 18; two-hour mean resampling yields 1, 5, 9, 13, 17.
    assert stored_report.values.T.tolist() == [[1, 5, 9, 13, 17]]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_worker_reports_nothing_saved_for_misaligned_inputs(
    app, fresh_db, setup_report_sensors_fresh_db, clean_redis, caplog, requesting_user
):
    """A report whose inputs do not share a source computes only NaN, which is not saved.

    The job result should exclude rows that persistence drops.
    """
    sensors = setup_report_sensors_fresh_db
    # An hourly output sensor lets the sum be recorded without resampling, which would drop the NaN rows early.
    hourly_output = Sensor(
        "hourly report output",
        generic_asset=sensors["asset"],
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    # Two sources, so the inputs do not align on the source level of their belief index.
    source_1 = DataSource("report input source 1")
    source_2 = DataSource("report input source 2")
    fresh_db.session.add_all([hourly_output, source_1, source_2])
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
            for sensor, source in (
                (sensors["input_1"], source_1),
                (sensors["input_2"], source_2),
            )
            for hour in range(10)
        ]
    fresh_db.session.add_all(beliefs)
    fresh_db.session.commit()

    # Sum the inputs without resampling, so that the NaN rows survive to be offered to the database.
    message = report_message(sensors["input_1"], sensors["input_2"], hourly_output)
    message["config"]["transformations"] = [
        {"df_input": "one", "method": "add", "args": ["@two"], "df_output": "sum"}
    ]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 202

    with caplog.at_level(logging.WARNING):
        work_on_rq(app.queues["reporting"])

    stored_report = hourly_output.search_beliefs(
        event_starts_after="2023-04-10T00:00:00+00:00",
        event_ends_before="2023-04-10T10:00:00+00:00",
    )
    assert len(stored_report) == 0, "misaligned inputs cannot produce stored values"

    job = app.queues["reporting"].fetch_job(response.json["job"])
    assert job.get_status() == "finished"
    # The count must exclude computed rows that persistence drops as NaN.
    assert job.return_value() == [
        {
            "sensor_id": hourly_output.id,
            "n_rows": 0,
        }
    ]
    assert any(
        "produced no persistable values" in record.message for record in caplog.records
    ), "an empty report should be warned about"


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_report_worker_fails_for_incompatible_units(
    app, fresh_db, setup_report_sensors_fresh_db, clean_redis, requesting_user
):
    """A reporter that expects power data must reject a currency input."""
    sensors = setup_report_sensors_fresh_db
    sensors["input_1"].unit = "EUR"
    fresh_db.session.commit()

    message = report_message(sensors["input_1"], sensors["input_2"], sensors["output"])
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_report", id=sensors["asset"].id), json=message
        )
    assert response.status_code == 202

    work_on_rq(app.queues["reporting"])

    job = app.queues["reporting"].fetch_job(response.json["job"])
    assert job.get_status() == JobStatus.FAILED
    assert (
        "Unit conversion from EUR to kW doesn't seem possible"
        in job.latest_result().exc_string
    )

    with app.test_client() as client:
        status_response = client.get(response.json["job-url"])
    assert status_response.status_code == 422
    assert status_response.json["status"] == "FAILED"
    assert "Unit conversion from EUR to kW" in status_response.json["exc-info"]
