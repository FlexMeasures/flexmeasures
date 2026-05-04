from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas.testing as pdt

from flexmeasures.data.services.data_ingestion import (
    add_beliefs_to_db_and_enqueue_forecasting_jobs,
    deserialize_ingestion_data,
    serialize_ingestion_data,
)
from flexmeasures.data.tests.utils import exception_reporter
from flexmeasures.tests.utils import get_test_sensor
from flexmeasures.utils.job_utils import work_on_rq


def _to_comparable_df(bdf):
    df = bdf.convert_index_from_belief_horizon_to_time().reset_index()
    df["source_id"] = df["source"].map(lambda s: s.id)
    return (
        df[
            [
                "event_start",
                "belief_time",
                "source_id",
                "cumulative_probability",
                "event_value",
            ]
        ]
        .sort_values(
            [
                "event_start",
                "belief_time",
                "source_id",
                "cumulative_probability",
            ]
        )
        .reset_index(drop=True)
    )


def _is_primitive_payload(value) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, Mapping):
        return all(
            isinstance(k, str) and _is_primitive_payload(v) for k, v in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_is_primitive_payload(v) for v in value)
    return False


def test_serialize_ingestion_data_uses_primitive_types(setup_beliefs, db):
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False).iloc[
        :2
    ]

    payload = serialize_ingestion_data(bdf)

    assert _is_primitive_payload(payload)


def test_ingestion_data_roundtrip_preserves_beliefs(setup_beliefs, db):
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False).iloc[
        :2
    ]

    payload = serialize_ingestion_data(bdf)
    restored = deserialize_ingestion_data(payload)

    assert len(restored) == 1
    pdt.assert_frame_equal(
        _to_comparable_df(restored[0]),
        _to_comparable_df(bdf),
        check_dtype=False,
    )


def test_ingestion_service_accepts_serialized_data(setup_beliefs, db):
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False).iloc[
        :1
    ]

    status = add_beliefs_to_db_and_enqueue_forecasting_jobs(
        serialized_data=serialize_ingestion_data(bdf),
        save_changed_beliefs_only=True,
    )

    assert status == "success_but_nothing_new"


def test_ingestion_job_succeeds_via_rq_worker(app, setup_beliefs, db):
    """Regression test: ingestion job must succeed when processed by an RQ worker.

    Without db.engine.dispose() the forked worker inherits stale SQLAlchemy
    connections from the parent process, causing the job to fail.
    """
    sensor = get_test_sensor(db)
    # A single belief is sufficient to exercise the worker's DB connection handling.
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False).iloc[
        :1
    ]
    serialized = serialize_ingestion_data(bdf)

    app.queues["ingestion"].enqueue(
        add_beliefs_to_db_and_enqueue_forecasting_jobs,
        serialized_data=serialized,
        save_changed_beliefs_only=True,
    )

    work_on_rq(app.queues["ingestion"], exc_handler=exception_reporter)

    assert app.queues["ingestion"].failed_job_registry.count == 0


def test_deserialize_ingestion_data_handles_mixed_timezone_offsets(setup_beliefs, db):
    sensor = get_test_sensor(db)
    source = sensor.search_beliefs(source="ENTSO-E").lineage.sources[0]
    payload = [
        {
            "sensor_id": sensor.id,
            "beliefs": [
                {
                    "event_start": "2021-03-28T01:00:00+01:00",
                    "belief_time": "2021-03-27T12:00:00+01:00",
                    "source_id": source.id,
                    "cumulative_probability": 0.5,
                    "event_value": 21.0,
                },
                {
                    "event_start": "2021-03-28T03:00:00+02:00",
                    "belief_time": "2021-03-27T13:00:00+02:00",
                    "source_id": source.id,
                    "cumulative_probability": 0.5,
                    "event_value": 22.0,
                },
            ],
        }
    ]

    restored = deserialize_ingestion_data(payload)

    assert len(restored) == 1
    assert restored[0].event_starts.tz is not None
    assert str(restored[0].event_starts.tz) in ("UTC", "UTC+00:00")
