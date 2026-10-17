"""
Logic around data ingestion (jobs)
"""

from __future__ import annotations

from io import BytesIO

from flask import current_app
from rq.job import Job
from rq.job import NoSuchJobError
from sqlalchemy.exc import IntegrityError
import timely_beliefs as tb
from werkzeug.datastructures import FileStorage

from flexmeasures.data import db
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import User
from flexmeasures.data.utils import (
    SAVE_TO_DB_SUCCESS_WITH_CHANGES_STATUSES,
    save_to_db,
)

UNIQUE_VIOLATION = "23505"  # SQLSTATE

BELIEF_REPLACEMENT_NOT_ALLOWED_MESSAGE = (
    "Some of the data represents a replacement: existing values would be changed for the same sensor, source, event timestamp and belief time. "
    "This is reserved for customized servers. "
    "If you are hosting FlexMeasures, you can enable replacements by setting FLEXMEASURES_ALLOW_DATA_OVERWRITE=True in the configuration settings. "
    "Alternatively, submit the data with a different prior, or check whether the same file was already uploaded with different values."
)


class BeliefReplacementNotAllowed(Exception):
    """Saving would change existing beliefs, which this server does not allow."""

    def __init__(self, message: str = BELIEF_REPLACEMENT_NOT_ALLOWED_MESSAGE):
        super().__init__(message)


def is_belief_replacement(error: IntegrityError) -> bool:
    """Tell whether an IntegrityError is a UniqueViolation on the TimedBelief primary key.

    The error is recognised by its SQLSTATE rather than by its class,
    because the class depends on the database driver:
    psycopg2 exposes the SQLSTATE as pgcode, and psycopg 3 as sqlstate.
    """
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
        error.orig, "pgcode", None
    )
    return sqlstate == UNIQUE_VIOLATION and "timed_belief_pkey" in str(error.orig)


def _get_ingestion_context(sensor_id: int, user_id: int) -> tuple[Sensor, User]:
    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValueError(f"No such sensor: {sensor_id}")
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError(f"No such user: {user_id}")
    return sensor, user


def _load_json_sensor_data(
    sensor_id: int,
    user_id: int,
    sensor_data: dict,
) -> tb.BeliefsDataFrame:
    """Validate and transform raw JSON sensor data into a BeliefsDataFrame."""

    from flexmeasures.api.common.schemas.sensor_data import PostSensorDataSchema

    _sensor, user = _get_ingestion_context(sensor_id, user_id)
    payload = dict(sensor_data)
    payload.pop("id", None)
    payload["sensor"] = sensor_id
    return PostSensorDataSchema(source_user=user).load(payload)["bdf"]


def _file_storage_from_payload(file_payload: dict) -> FileStorage:
    stream = BytesIO(file_payload["content"])
    stream.name = file_payload["filename"]
    return FileStorage(
        stream=stream,
        filename=file_payload["filename"],
        content_type=file_payload["content_type"],
    )


def _load_uploaded_sensor_data(
    sensor_id: int,
    user_id: int,
    uploaded_files: list[dict],
    upload_data: dict,
) -> list[tb.BeliefsDataFrame]:
    """Validate and transform raw uploaded files into BeliefsDataFrames."""

    from flexmeasures.data.schemas.sensors import SensorDataFileSchema

    _sensor, user = _get_ingestion_context(sensor_id, user_id)
    payload = dict(upload_data)
    payload["id"] = sensor_id
    payload["uploaded-files"] = [
        _file_storage_from_payload(file_payload) for file_payload in uploaded_files
    ]
    return SensorDataFileSchema(source_user=user).load(payload)["data"]


def _save_and_commit(
    data: tb.BeliefsDataFrame | list[tb.BeliefsDataFrame],
    save_changed_beliefs_only: bool,
) -> str:
    """Save beliefs and commit them.

    A refused replacement is raised by name, so a failed ingestion job reports it rather than the database error.
    """
    try:
        status = save_to_db(data, save_changed_beliefs_only=save_changed_beliefs_only)
        db.session.commit()
    except IntegrityError as error:
        if not is_belief_replacement(error):
            raise
        db.session.rollback()
        raise BeliefReplacementNotAllowed() from error
    return status


def add_beliefs_to_db_and_enqueue_forecasting_jobs(
    data: tb.BeliefsDataFrame | list[tb.BeliefsDataFrame] | None = None,
    sensor_id: int | None = None,
    user_id: int | None = None,
    sensor_data: dict | None = None,
    uploaded_files: list[dict] | None = None,
    upload_data: dict | None = None,
    forecasting_jobs: list[Job] | None = None,
    forecasting_job_ids: list[str] | None = None,
    save_changed_beliefs_only: bool = True,
) -> str:
    """Save sensor data to the database and optionally enqueue forecasting jobs.

    This function is intended to be called as an RQ job by an ingestion queue worker,
    but can also be called directly (e.g. as a fallback when no workers are available).

    :param data:                        BeliefsDataFrame (or list thereof) to be saved.
    :param sensor_id:                   Sensor ID for raw JSON or file ingestion.
    :param user_id:                     User ID used to resolve the source of raw ingested data.
    :param sensor_data:                 Raw JSON payload from the sensor data endpoint.
    :param uploaded_files:              Uploaded file contents and metadata.
    :param upload_data:                 Raw form payload from the sensor data upload endpoint.
    :param forecasting_jobs:            Optional list of forecasting Jobs to enqueue after saving.
    :param forecasting_job_ids:         Optional list of forecasting Job ids to enqueue after saving.
    :param save_changed_beliefs_only:   If True, skip saving beliefs whose value hasn't changed.
    :returns:                           Status string as returned by ``save_to_db``.
    :raises BeliefReplacementNotAllowed: if saving would change existing beliefs, while FLEXMEASURES_ALLOW_DATA_OVERWRITE is off.
    """
    if sensor_data is not None:
        if sensor_id is None or user_id is None:
            raise ValueError("Expected sensor_id and user_id for raw sensor data.")
        data = _load_json_sensor_data(sensor_id, user_id, sensor_data)
    elif uploaded_files is not None:
        if sensor_id is None or user_id is None:
            raise ValueError("Expected sensor_id and user_id for uploaded sensor data.")
        data = _load_uploaded_sensor_data(
            sensor_id,
            user_id,
            uploaded_files,
            upload_data or {},
        )
    if data is None:
        raise ValueError("Expected data, sensor_data, or uploaded_files.")

    status = _save_and_commit(data, save_changed_beliefs_only=save_changed_beliefs_only)

    # Only enqueue forecasting jobs upon successfully saving new data
    if status in SAVE_TO_DB_SUCCESS_WITH_CHANGES_STATUSES:
        if forecasting_jobs is not None:
            for job in forecasting_jobs:
                current_app.queues["forecasting"].enqueue_job(job)
        if forecasting_job_ids is not None:
            connection = current_app.queues["forecasting"].connection
            for job_id in forecasting_job_ids:
                try:
                    job = Job.fetch(job_id, connection=connection)
                except NoSuchJobError:
                    current_app.logger.warning(
                        "Forecasting job %s no longer exists; skipping enqueue.",
                        job_id,
                    )
                    continue
                current_app.queues["forecasting"].enqueue_job(job)

    return status
