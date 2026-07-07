from __future__ import annotations

from sqlalchemy import select, event
from fakeredis import FakeStrictRedis

from flexmeasures.data.models.time_series import Sensor


def get_test_sensor(db) -> Sensor | None:
    sensor = db.session.execute(
        select(Sensor).filter_by(name="epex_da")
    ).scalar_one_or_none()
    return sensor


class QueryCounter(object):
    """Context manager to count SQLALchemy queries."""

    def __init__(self, connection):
        self.connection = connection.engine
        self.count = 0

    def __enter__(self):
        event.listen(self.connection, "before_cursor_execute", self.callback)
        return self

    def __exit__(self, *args, **kwargs):
        event.remove(self.connection, "before_cursor_execute", self.callback)

    def callback(self, *args, **kwargs):
        self.count += 1


class RQCompatibleFakeStrictRedis(FakeStrictRedis):
    """
    A fake Redis client that is compatible with RQ >= 2.9.0.
    """

    def client_list(self, *args, **kwargs):
        clients = super().client_list(*args, **kwargs)
        for client in clients:
            client.setdefault("addr", "fakeredis:0")
        return clients
