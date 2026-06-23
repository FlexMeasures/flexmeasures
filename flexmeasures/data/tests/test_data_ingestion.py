from __future__ import annotations

from flexmeasures.data.services.data_ingestion import (
    add_beliefs_to_db_and_enqueue_forecasting_jobs,
)
from flexmeasures.data.utils import SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW
from flexmeasures.tests.utils import get_test_sensor


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
