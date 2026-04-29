from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas.testing as pdt

from flexmeasures.data.services.data_ingestion import (
    add_beliefs_to_db_and_enqueue_forecasting_jobs,
    deserialize_ingestion_data,
    serialize_ingestion_data,
)
from flexmeasures.tests.utils import get_test_sensor


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
