"""
Logic around data ingestion (jobs)
"""

from __future__ import annotations

from collections.abc import Sequence

from flask import current_app
import pandas as pd
from rq.job import Job
from rq.job import NoSuchJobError
from sqlalchemy import select
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import save_to_db


def _to_utc_iso(dt) -> str:
    """Serialize a datetime-like value as an ISO string in UTC."""
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def serialize_ingestion_data(
    data: tb.BeliefsDataFrame | list[tb.BeliefsDataFrame],
) -> list[dict]:
    """Serialize beliefs data to primitive types suitable for queue kwargs.

    The returned payload intentionally avoids ORM instances (Sensor/DataSource),
    which can break across process boundaries when pickled by RQ.
    """

    bdfs: list[tb.BeliefsDataFrame]
    if isinstance(data, list):
        bdfs = data
    else:
        bdfs = [data]

    payload: list[dict] = []
    for bdf in bdfs:
        # Normalize timing representation to belief_time for stable serialization.
        bdf = bdf.convert_index_from_belief_horizon_to_time()
        serialized_rows: list[dict] = []
        for belief in bdf.reset_index().itertuples(index=False):
            serialized_rows.append(
                {
                    "event_start": _to_utc_iso(belief.event_start),
                    "belief_time": _to_utc_iso(belief.belief_time),
                    "source_id": belief.source.id,
                    "cumulative_probability": float(belief.cumulative_probability),
                    "event_value": (
                        None
                        if pd.isna(belief.event_value)
                        else float(belief.event_value)
                    ),
                }
            )

        payload.append(
            {
                "sensor_id": bdf.sensor.id,
                "beliefs": serialized_rows,
            }
        )
    return payload


def deserialize_ingestion_data(payload: Sequence[dict]) -> list[tb.BeliefsDataFrame]:
    """Deserialize queue-safe ingestion payload back into BeliefsDataFrames."""

    bdfs: list[tb.BeliefsDataFrame] = []
    for item in payload:
        sensor = db.session.get(Sensor, item["sensor_id"])
        if sensor is None:
            raise ValueError(f"No such sensor: {item['sensor_id']}")

        belief_rows = item.get("beliefs", [])
        if not belief_rows:
            bdfs.append(tb.BeliefsDataFrame(sensor=sensor))
            continue

        source_ids = sorted({row["source_id"] for row in belief_rows})
        sources = db.session.scalars(
            select(DataSource).filter(DataSource.id.in_(source_ids))
        ).all()
        source_map = {source.id: source for source in sources}

        beliefs: list[TimedBelief] = []
        for row in belief_rows:
            source = source_map.get(row["source_id"])
            if source is None:
                raise ValueError(f"No such source: {row['source_id']}")
            beliefs.append(
                TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=pd.to_datetime(row["event_start"], utc=True),
                    belief_time=pd.to_datetime(row["belief_time"], utc=True),
                    cumulative_probability=row["cumulative_probability"],
                    event_value=row["event_value"],
                )
            )
        bdfs.append(tb.BeliefsDataFrame(beliefs))

    return bdfs


def add_beliefs_to_db_and_enqueue_forecasting_jobs(
    data: tb.BeliefsDataFrame | list[tb.BeliefsDataFrame] | None = None,
    serialized_data: list[dict] | None = None,
    forecasting_jobs: list[Job] | None = None,
    forecasting_job_ids: list[str] | None = None,
    save_changed_beliefs_only: bool = True,
) -> str:
    """Save sensor data to the database and optionally enqueue forecasting jobs.

    This function is intended to be called as an RQ job by an ingestion queue worker,
    but can also be called directly (e.g. as a fallback when no workers are available).

    :param data:                        BeliefsDataFrame (or list thereof) to be saved.
    :param serialized_data:             Queue-safe payload containing only primitive types.
    :param forecasting_jobs:            Optional list of forecasting Jobs to enqueue after saving.
    :param forecasting_job_ids:         Optional list of forecasting Job ids to enqueue after saving.
    :param save_changed_beliefs_only:   If True, skip saving beliefs whose value hasn't changed.
    :returns:                           Status string, one of:
                                        - 'success'
                                        - 'success_with_unchanged_beliefs_skipped'
                                        - 'success_but_nothing_new'
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    if serialized_data is not None:
        data = deserialize_ingestion_data(serialized_data)
    if data is None:
        raise ValueError("Expected either data or serialized_data.")

    status = save_to_db(data, save_changed_beliefs_only=save_changed_beliefs_only)
    db.session.commit()

    # Only enqueue forecasting jobs upon successfully saving new data
    if status[:7] == "success" and status != "success_but_nothing_new":
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
