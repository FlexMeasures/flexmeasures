from __future__ import annotations

from sqlalchemy import select

from flexmeasures.data.models.time_series import Sensor


def get_test_sensor(db) -> Sensor | None:
    sensor = db.session.execute(
        select(Sensor).filter_by(name="epex_da")
    ).scalar_one_or_none()
    return sensor
