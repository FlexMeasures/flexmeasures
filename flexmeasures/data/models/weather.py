from typing import Dict, Tuple

import timely_beliefs as tb
from sqlalchemy.orm import Query
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.sql.expression import func
from sqlalchemy.schema import UniqueConstraint

from flexmeasures.data import db
from flexmeasures.data.models.legacy_migration_utils import (
    copy_old_sensor_attributes,
    get_old_model_type,
)
from flexmeasures.data.models.time_series import Sensor, TimedValue, TimedBelief
from flexmeasures.data.models.generic_assets import (
    create_generic_asset,
    GenericAsset,
    GenericAssetType,
)
from flexmeasures.utils import geo_utils
from flexmeasures.utils.entity_address_utils import build_entity_address
from flexmeasures.utils.flexmeasures_inflection import humanize


class WeatherSensorType(db.Model):
    """
    This model is now considered legacy. See GenericAssetType.
    """

    name = db.Column(db.String(80), primary_key=True)
    display_name = db.Column(db.String(80), default="", unique=True)

    daily_seasonality = True
    weekly_seasonality = False
    yearly_seasonality = True

    def __init__(self, **kwargs):
        generic_asset_type = GenericAssetType(
            name=kwargs["name"], description=kwargs.get("hover_label", None)
        )
        db.session.add(generic_asset_type)
        super(WeatherSensorType, self).__init__(**kwargs)
        self.name = self.name.replace(" ", "_").lower()
        if "display_name" not in kwargs:
            self.display_name = humanize(self.name)

    def __repr__(self):
        return "<WeatherSensorType %r>" % self.name


class WeatherSensor(db.Model, tb.SensorDBMixin):
    """
    A weather sensor has a location on Earth and measures weather values of a certain weather sensor type, such as
    temperature, wind speed and radiation.

    This model is now considered legacy. See GenericAsset and Sensor.
    """

    id = db.Column(
        db.Integer, db.ForeignKey("sensor.id"), primary_key=True, autoincrement=True
    )
    name = db.Column(db.String(80), unique=True)
    display_name = db.Column(db.String(80), default="", unique=False)
    weather_sensor_type_name = db.Column(
        db.String(80), db.ForeignKey("weather_sensor_type.name"), nullable=False
    )
    # latitude is the North/South coordinate
    latitude = db.Column(db.Float, nullable=False)
    # longitude is the East/West coordinate
    longitude = db.Column(db.Float, nullable=False)

    # only one sensor of any type is needed at one location
    __table_args__ = (
        UniqueConstraint(
            "weather_sensor_type_name",
            "latitude",
            "longitude",
            name="weather_sensor_type_name_latitude_longitude_key",
        ),
    )

    def __init__(self, **kwargs):
        kwargs["name"] = kwargs["name"].replace(" ", "_").lower()

        super(WeatherSensor, self).__init__(**kwargs)

        # Create a new Sensor with unique id across assets, markets and weather sensors
        if "id" not in kwargs:

            weather_sensor_type = get_old_model_type(
                kwargs,
                WeatherSensorType,
                "weather_sensor_type_name",
                "sensor_type",  # NB not "weather_sensor_type" (slight inconsistency in this old sensor class)
            )

            generic_asset_kwargs = {
                **kwargs,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[],
                    old_sensor_attributes=[
                        "display_name",
                    ],
                    old_sensor_type=weather_sensor_type,
                ),
            }
            new_generic_asset = create_generic_asset(
                "weather_sensor", **generic_asset_kwargs
            )
            new_sensor = Sensor(
                name=kwargs["name"],
                generic_asset=new_generic_asset,
                **copy_old_sensor_attributes(
                    self,
                    old_sensor_type_attributes=[
                        "daily_seasonality",
                        "weekly_seasonality",
                        "yearly_seasonality",
                    ],
                    old_sensor_attributes=[
                        "display_name",
                    ],
                    old_sensor_type=weather_sensor_type,
                ),
            )
            db.session.add(new_sensor)
            db.session.flush()  # generates the pkey for new_sensor
            new_sensor_id = new_sensor.id
        else:
            # The UI may initialize WeatherSensor objects from API form data with a known id
            new_sensor_id = kwargs["id"]

        self.id = new_sensor_id

        # Copy over additional columns from (newly created) WeatherSensor to (newly created) Sensor
        if "id" not in kwargs:
            db.session.add(self)
            db.session.flush()  # make sure to generate each column for the old sensor
            new_sensor.unit = self.unit
            new_sensor.event_resolution = self.event_resolution
            new_sensor.knowledge_horizon_fnc = self.knowledge_horizon_fnc
            new_sensor.knowledge_horizon_par = self.knowledge_horizon_par

    @property
    def entity_address_fm0(self) -> str:
        """Entity address under the fm0 scheme for entity addresses."""
        return build_entity_address(
            dict(
                weather_sensor_type_name=self.weather_sensor_type_name,
                latitude=self.latitude,
                longitude=self.longitude,
            ),
            "weather_sensor",
            fm_scheme="fm0",
        )

    @property
    def entity_address(self) -> str:
        """Entity address under the latest fm scheme for entity addresses."""
        return build_entity_address(
            dict(sensor_id=self.id),
            "sensor",
        )

    @property
    def corresponding_sensor(self) -> Sensor:
        return db.session.query(Sensor).get(self.id)

    @property
    def generic_asset(self) -> GenericAsset:
        return db.session.query(GenericAsset).get(self.corresponding_sensor.id)

    def get_attribute(self, attribute: str):
        """Looks for the attribute on the corresponding Sensor.

        This should be used by all code to read these attributes,
        over accessing them directly on this class,
        as this table is in the process to be replaced by the Sensor table.
        """
        return self.corresponding_sensor.get_attribute(attribute)

    @property
    def weather_unit(self) -> float:
        """Return the 'unit' property of the generic asset, just with a more insightful name."""
        return self.unit

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude

    @hybrid_method
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (in km).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return geo_utils.earth_distance(self.location, other_location)

    @great_circle_distance.expression
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (unclear if in km or in miles).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return func.earth_distance(
            func.ll_to_earth(self.latitude, self.longitude),
            func.ll_to_earth(*other_location),
        )

    sensor_type = db.relationship(
        "WeatherSensorType", backref=db.backref("sensors", lazy=True)
    )

    def __repr__(self):
        return "<WeatherSensor %s:%r (%r), res.:%s>" % (
            self.id,
            self.name,
            self.weather_sensor_type_name,
            self.event_resolution,
        )

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, sensor_type=self.weather_sensor_type_name)


class Weather(TimedValue, db.Model):
    """
    All weather measurements are stored in one slim table.

    This model is now considered legacy. See TimedBelief.
    """

    sensor_id = db.Column(
        db.Integer(), db.ForeignKey("sensor.id"), primary_key=True, index=True
    )
    sensor = db.relationship("Sensor", backref=db.backref("weather", lazy=True))

    @classmethod
    def make_query(cls, **kwargs) -> Query:
        """Construct the database query."""
        return super().make_query(**kwargs)

    def __init__(self, use_legacy_kwargs: bool = True, **kwargs):

        # todo: deprecate the 'Weather' class in favor of 'TimedBelief' (announced v0.8.0)
        if use_legacy_kwargs is False:

            # Create corresponding TimedBelief
            belief = TimedBelief(**kwargs)
            db.session.add(belief)

            # Convert key names for legacy model
            kwargs["value"] = kwargs.pop("event_value")
            kwargs["datetime"] = kwargs.pop("event_start")
            kwargs["horizon"] = kwargs.pop("belief_horizon")
            kwargs["sensor_id"] = kwargs.pop("sensor").id
            kwargs["data_source_id"] = kwargs.pop("source").id
        else:
            import warnings

            warnings.warn(
                f"The {self.__class__} class is deprecated. Switch to using the TimedBelief class to suppress this warning.",
                FutureWarning,
            )

        super(Weather, self).__init__(**kwargs)

    def __repr__(self):
        return "<Weather %.5f on Sensor %s at %s by DataSource %s, horizon %s>" % (
            self.value,
            self.sensor_id,
            self.datetime,
            self.data_source_id,
            self.horizon,
        )
