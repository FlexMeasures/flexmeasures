from typing import Dict, Tuple, Union
from datetime import datetime, timedelta
import math

from sqlalchemy.orm import Query, Session
from sqlalchemy.ext.hybrid import hybrid_method, hybrid_property
from sqlalchemy.sql.expression import func

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.time_series import TimedValue
from bvp.utils.geo_utils import parse_lat_lng


class WeatherSensorType(db.Model):
    """"
    TODO: Add useful attributes like ...?
    """

    name = db.Column(db.String(80), primary_key=True)

    def __repr__(self):
        return "<WeatherSensorType %r>" % self.name


class WeatherSensor(db.Model):
    """A weather sensor has a location on Earth and measures weather values of a certain weather sensor type, such as
    temperature, wind speed and radiation."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    weather_sensor_type_name = db.Column(
        db.String(80), db.ForeignKey("weather_sensor_type.name"), nullable=False
    )
    # latitude is the North/South coordinate
    latitude = db.Column(db.Float, nullable=False)
    # longitude is the East/West coordinate
    longitude = db.Column(db.Float, nullable=False)

    def __init__(self, **kwargs):
        super(WeatherSensor, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude

    @hybrid_property
    def cos_rad_lat(self):
        return math.cos(math.radians(self.latitude))

    @hybrid_property
    def sin_rad_lat(self):
        return math.sin(math.radians(self.latitude))

    @hybrid_property
    def rad_lng(self):
        return math.radians(self.longitude)

    @hybrid_method
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (in km).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        """
        r = 6371  # Radius of Earth in kilometers
        other_latitude, other_longitude = parse_lat_lng(kwargs)
        if other_latitude is None or other_longitude is None:
            return None
        other_cos_rad_lat = math.cos(math.radians(other_latitude))
        other_sin_rad_lat = math.sin(math.radians(other_latitude))
        other_rad_lng = math.radians(other_longitude)
        return (
            math.acos(
                self.cos_rad_lat
                * other_cos_rad_lat
                * math.cos(self.rad_lng - other_rad_lng)
                + self.sin_rad_lat * other_sin_rad_lat
            )
            * r
        )

    @great_circle_distance.expression
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (unclear if in km or in miles).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

         """
        other_latitude, other_longitude = parse_lat_lng(kwargs)
        if other_latitude is None or other_longitude is None:
            return None
        return func.earth_distance(
            func.ll_to_earth(self.latitude, self.longitude),
            func.ll_to_earth(other_latitude, other_longitude),
        )

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
        rolling: bool = False,
        session: Session = None,
    ) -> Query:
        if session is None:
            session = db.session
        start, end = query_window
        # Todo: get data resolution for the weather sensor
        resolution = timedelta(minutes=15)
        start = (
            start - resolution
        )  # Adjust for the fact that we index time slots by their start time
        query = (
            session.query(cls.datetime, cls.value, cls.horizon, DataSource.label)
            .join(DataSource)
            .filter(cls.data_source_id == DataSource.id)
            .join(WeatherSensor)
            .filter(WeatherSensor.name == sensor_name)
            .filter((Weather.datetime > start) & (Weather.datetime < end))
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

    def __init__(self, **kwargs):
        super(Weather, self).__init__(**kwargs)
