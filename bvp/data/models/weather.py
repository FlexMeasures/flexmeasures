from typing import Dict, Tuple, Union
from datetime import datetime, timedelta

from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.models.time_series import TimedValue


class WeatherSensorType(db.Model):
    """"
    TODO: Add useful attributes like ...?
    """

    name = db.Column(db.String(80), primary_key=True)

    def __repr__(self):
        return "<WeatherSensorType %r>" % self.name


class WeatherSensor(db.Model):
    """
    TODO: Add useful attributes like ...?
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    weather_sensor_type_name = db.Column(
        db.String(80), db.ForeignKey("weather_sensor_type.name"), nullable=False
    )

    def __init__(self, **kwargs):
        super(WeatherSensor, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()

    sensor_type = db.relationship(
        "WeatherSensorType", backref=db.backref("sensors", lazy=True)
    )

    def __repr__(self):
        return "<WeatherSensor %r (%r)>" % (self.name, self.weather_sensor_type_name)

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, sensor_type=self.weather_sensor_type_name)


class Weather(TimedValue, db.Model):
    """
    All weather measurements are stored in one slim table.
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    """

    sensor_id = db.Column(
        db.Integer(), db.ForeignKey("weather_sensor.id"), primary_key=True
    )
    sensor = db.relationship("WeatherSensor", backref=db.backref("weather", lazy=True))

    @classmethod
    def make_query(
        cls,
        sensor_name: str,
        query_window: Tuple[datetime, datetime],
        horizon_window: Tuple[Union[None, timedelta], Union[None, timedelta]] = (
            None,
            None,
        ),
        session: Session = None,
    ) -> Query:
        if session is None:
            session = db.session
        start, end = query_window
        query = (
            session.query(cls.datetime, cls.value)
            .join(WeatherSensor)
            .filter(WeatherSensor.name == sensor_name)
            .filter((Weather.datetime >= start) & (Weather.datetime <= end))
        )
        earliest_horizon, latest_horizon = horizon_window
        if (
            earliest_horizon is not None
            and latest_horizon is not None
            and earliest_horizon == latest_horizon
        ):
            query = query.filter(Weather.horizon == earliest_horizon)
        else:
            if earliest_horizon is not None:
                query = query.filter(Weather.horizon >= earliest_horizon)
            if latest_horizon is not None:
                query = query.filter(Weather.horizon <= latest_horizon)
        return query
