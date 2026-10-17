from __future__ import annotations

from datetime import timedelta

from marshmallow import ValidationError
import pandas as pd
import pytest

from flexmeasures.data.services.data_ingestion import (
    BELIEF_REPLACEMENT_NOT_ALLOWED_MESSAGE,
    BeliefReplacementNotAllowed,
    add_beliefs_to_db_and_enqueue_forecasting_jobs,
)
from flexmeasures.data.utils import (
    SAVE_TO_DB_SUCCESS,
    SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW,
)
from flexmeasures.tests.utils import get_test_sensor
from flexmeasures.utils.time_utils import server_now


def test_ingestion_service_accepts_beliefs_data_frame(setup_beliefs, db):
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False).iloc[
        :1
    ]

    status = add_beliefs_to_db_and_enqueue_forecasting_jobs(
        data=bdf,
        save_changed_beliefs_only=True,
    )

    assert status == SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW


def test_ingestion_job_accepts_prior_ahead_of_its_clock(
    setup_beliefs_fresh_db, setup_roles_users_fresh_db, fresh_db
):
    """A queued upload is saved even if the server that received it ran ahead of the worker's clock."""
    sensor = get_test_sensor(fresh_db)
    user_id = setup_roles_users_fresh_db["Test Prosumer User"]
    belief_time = server_now() + timedelta(minutes=1)

    status = add_beliefs_to_db_and_enqueue_forecasting_jobs(
        sensor_id=sensor.id,
        user_id=user_id,
        uploaded_files=[
            dict(
                filename="prices.csv",
                content_type="text/csv",
                content=b"event_start,event_value\n2030-01-01T00:00:00+00:00,10\n2030-01-01T01:00:00+00:00,20\n",
            )
        ],
        upload_data={
            "belief-time-measured-instantly": "off",
            "prior": belief_time.isoformat(),
        },
    )

    assert status == SAVE_TO_DB_SUCCESS
    bdf = sensor.search_beliefs(
        event_starts_after=pd.Timestamp("2030-01-01T00:00:00Z"),
        most_recent_beliefs_only=False,
    )
    assert bdf.reset_index()["belief_time"].tolist() == [pd.Timestamp(belief_time)] * 2


@pytest.mark.parametrize(
    "event_start, refused",
    [
        ("2030-01-01T00:00:00+00:00", True),
        ("2020-01-01T00:00:00+00:00", False),
    ],
)
def test_ingestion_job_refuses_belief_times_after_the_request(
    setup_beliefs_fresh_db, setup_roles_users_fresh_db, fresh_db, event_start, refused
):
    """A measured-instantly upload is refused if any value is recorded after the time of the request."""
    sensor = get_test_sensor(fresh_db)

    def ingest():
        return add_beliefs_to_db_and_enqueue_forecasting_jobs(
            sensor_id=sensor.id,
            user_id=setup_roles_users_fresh_db["Test Prosumer User"],
            uploaded_files=[
                dict(
                    filename="prices.csv",
                    content_type="text/csv",
                    content=f"event_start,event_value\n{event_start},10\n".encode(),
                )
            ],
            upload_data={"belief-time-measured-instantly": "on"},
            refuse_belief_times_after=server_now(),
        )

    if refused:
        with pytest.raises(ValidationError, match="lies in the future"):
            ingest()
    else:
        assert ingest() == SAVE_TO_DB_SUCCESS


def test_ingestion_refuses_replacement_by_name(
    setup_beliefs_fresh_db, setup_roles_users_fresh_db, fresh_db
):
    """Changing values at an existing belief time is refused with a readable error, not a database error."""
    sensor = get_test_sensor(fresh_db)

    def upload(value: int) -> str:
        return add_beliefs_to_db_and_enqueue_forecasting_jobs(
            sensor_id=sensor.id,
            user_id=setup_roles_users_fresh_db["Test Prosumer User"],
            uploaded_files=[
                dict(
                    filename="prices.csv",
                    content_type="text/csv",
                    content=f"event_start,event_value\n2030-01-01T00:00:00+00:00,{value}\n".encode(),
                )
            ],
            upload_data={
                "belief-time-measured-instantly": "off",
                "prior": "2026-01-01T00:00:00+00:00",
            },
        )

    assert upload(10) == SAVE_TO_DB_SUCCESS
    with pytest.raises(BeliefReplacementNotAllowed) as exc_info:
        upload(11)
    assert str(exc_info.value) == BELIEF_REPLACEMENT_NOT_ALLOWED_MESSAGE

    # The session was rolled back, so it can still be used, and the first value stands
    bdf = sensor.search_beliefs(
        event_starts_after=pd.Timestamp("2030-01-01T00:00:00Z"),
        most_recent_beliefs_only=False,
    )
    assert bdf["event_value"].tolist() == [10]
