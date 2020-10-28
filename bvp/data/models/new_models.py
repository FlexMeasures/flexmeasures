from datetime import datetime, timedelta
import json
from typing import List, Optional, Tuple, Union

from bvp.data.config import db
from pandas._libs.tslibs.offsets import prefix_mapping
from pandas.tseries.frequencies import to_offset
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy_json import mutable_json_type
import pandas as pd
import timely_beliefs as tb


STANDARD_OFFSET_NAMES = [
    kwarg
    for kwarg in pd.offsets.DateOffset.__init__.__objclass__._attributes
    if kwarg not in ["n", "normalize"]
]
NON_STANDARD_OFFSET_NAMES = pd.tseries.offsets.__all__
NON_STANDARD_OFFSET_NAMES = prefix_mapping.keys()


class DataSource(db.Model, tb.BeliefSourceDBMixin):
    """A data source is a data-providing entity."""

    __tablename__ = "data_sources"

    # Can be set by user to distinguish scenarios
    label = db.Column(db.String(80), default="")

    # The responsible actuator
    actuator_id = db.Column(
        db.Integer, db.ForeignKey("actuator.id"), nullable=False, unique=False
    )
    actuator = db.relationship(
        "Actuator",
        foreign_keys=[actuator_id],
        backref=db.backref("data_sources", lazy=True),
    )

    # The responsible user, if any
    #   although nullable, we do aim to track which user was responsible for triggering the actuator
    #   for example, if the actuator is triggered by a job, a user triggered the job (e.g. by posting to the API)
    #   and a little harder: if the actuator is triggered by a scheduled script, a user scheduled the script
    user_id = db.Column(
        db.Integer, db.ForeignKey("bvp_users.id"), nullable=True, unique=False
    )
    user = db.relationship(
        "User", foreign_keys=[user_id], backref=db.backref("data_sources", lazy=True)
    )

    # The assigned account (no shared data between accounts)
    account_id = db.Column(
        db.Integer, db.ForeignKey("bvp_accounts.id"), nullable=False, unique=False
    )
    # todo: account = db.relationship("Account", foreign_keys=[account_id], backref=db.backref("data_sources", lazy=True))

    @property
    def type(self):
        action_type = self.actuator.action_type
        if action_type == "post":
            return "user"
        return f"{action_type} script"


class Sensor(db.Model, tb.SensorDBMixin):
    """A sensor defines common properties of measured events.

    Examples of common event properties:
    - the event resolution: how long an event lasts, where timedelta(0) denotes an instantaneous state
    - the knowledge horizon: how long before (an event starts) the event could be known
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(
        db.Float, nullable=False
    )  # North/South coordinate; if null, check .asset.latitude
    longitude = db.Column(
        db.Float, nullable=False
    )  # East/West coordinate; if null, check .asset.longitude

    sensor_type_id = db.Column(
        db.Integer, db.ForeignKey("sensor_type.id"), nullable=False
    )
    sensor_type = db.relationship(
        "SensorType",
        foreign_keys=[sensor_type_id],
        backref=db.backref("sensors", lazy=True),
    )

    asset_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset = db.relationship(
        "Asset", foreign_keys=[asset_id], backref=db.backref("sensors", lazy=True)
    )

    @property
    def location(self) -> Tuple[float, float]:
        if not (self.latitude and self.longitude):
            return self.asset.latitude, self.asset.longitude
        return self.latitude, self.longitude

    @property
    def unit(self) -> str:
        return self.sensor_type.unit


class SensorType(db.Model):
    """A sensor type defines what type of data a sensor measures, and includes a unit.

    Examples of physical sensor types: temperature, wind speed, wind direction, pressure.
    Examples of economic sensor types: unit price, gross domestic product, cVaR.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    unit = db.Column(db.String(80), nullable=False)
    hover_label = db.Column(db.String(80), nullable=True, unique=False)


class Asset(db.Model):
    """An asset is something that has economic value.

    Examples of tangible assets: a house, a ship, a weather station.
    Examples of intangible assets: a market, a country, a copyright.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(db.Float, nullable=True)  # if null, asset is virtual
    longitude = db.Column(db.Float, nullable=True)  # if null, asset is virtual

    asset_type_id = db.Column(
        db.Integer, db.ForeignKey("asset_type.id"), nullable=False
    )
    asset_type = db.relationship(
        "AssetType",
        foreign_keys=[asset_type_id],
        backref=db.backref("assets", lazy=True),
    )

    owner_id = db.Column(
        db.Integer, db.ForeignKey("bvp_users.id", ondelete="CASCADE"), nullable=True
    )  # null means public asset
    owner = db.relationship(
        "User",
        backref=db.backref(
            "assets",
            foreign_keys=[owner_id],
            lazy=True,
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude

    @classmethod
    def get_processes(
        cls, time_window, duration_window
    ) -> Union["AggregatedProcess", "GeneralizedProcess"]:
        pass


class AssetType(db.Model):
    """An asset type defines what type an asset belongs to.

    Examples of asset types: WeatherStation, Market, CP, EVSE, WindTurbine, SolarPanel, Building.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    hover_label = db.Column(db.String(80), nullable=True, unique=False)


class SensorRelationship(db.Model):
    """A sensor relationship defines a functional dependency or constraint relationship between sensors.
    It can be used to define:
    - an equality constraint between 2 sensors (e.g. to let production follow contracted sales)
    - an inequality constraint between 2 sensors (e.g. to set a max capacity)
    - autoregressive relationships (e.g. for seasonal periodicity)
    - regressive relationships (possibly lagged) between 2 sensors
    - cost or utility functions formed by multiple sensors (e.g. to calculate retail utility)
    - polynomials formed by multiple sensors (e.g. to calculate compound interest)
    This can be used to describe functional dependency or constraint relationships between sensors.

    sensor1 depends on / is a function of sensor2, or sensor1 is constrained by sensor2.

    :param sensor1: Dependent variable (within the context of the described relationship).
    :param relationship_function:
                    One of "is_sum_of", "is_equal_or_less_than", "is", "is_equal_or_greater_than",
                    "is_product_of", "is_scored_by", "is_less_than", "is_greater_than" or "is_regressed_by".
    :param sensor2: Independent variable (within the context of the described relationship).
    :param d:       Optional duration: a pandas freqstr like "1B" (1 business day) or "15T" (15 minutes),
                    or a dictionary with dateutil.relativedelta keywords, such as:
                    {"months": 1, "day": 4}  # the 4th of the month
    :param k:       Optional scalar: a float.
    :param p:       Optional power: a float.
    :param config:  Optional dictionary to define the above and other config variables for the relationship
                    e.g. {"d": "15T}

    Equality constraints
    --------------------
    x_sensor1 == k * x_sensor2
    where k is an optional scalar (1 by default).

    For example, production should be equal to contracted sales
    >>> SensorRelationship(sensor1=Sensor("production"), relationship_function="is", sensor2=Sensor("contracted sales"))

    Inequality constraints
    ----------------------
    x_sensor1 <= k * x_sensor2, x_sensor1 < k * x_sensor2, x_sensor1 >= k * x_sensor2, x_sensor1 > k * x_sensor2
    where k is an optional scalar (1 by default).

    For example, production should be at most 70% of nominal capacity:
    >>> SensorRelationship(Sensor("production"), "is_equal_or_less_than", Sensor("nominal capacity"), config={"k": 0.7})  # k is an optional scalar

    Autoregressive relationships
    ----------------------------
    x(t)_sensor1 = f( k_1 * x(t - d_1)_sensor1 + k_2 * x(t - d_2)_sensor1 + ... + k_r * x(t - d_r)_sensor1 )
    where k is an optional scalar (1 by default), d is an optional duration (0 by default),
    and r is an implict count of the autoregressive relationships of sensor1.

    For example, solar production has daily and yearly seasonality:
    >>> SensorRelationship(Sensor("solar production"), "is_regressed_by", config={"d": "1D"})  # relationship r=1
    >>> SensorRelationship(Sensor("solar production"), "is_regressed_by", config={"d": "1Y"})  # relationship r=2

    Regressive relationships
    ------------------------
    x(t)_sensor1 = f( k_1 * x(t - d_1)_sensor2 + k_2 * x(t - d_2)_sensor2 + ... + k_r * x(t - d_r)_sensor2 )
    where k is an optional scalar (1 by default), d is an optional duration (0 by default),
    and r is an implict count of the regressive relationships of sensor1 on sensor2.

    For example, ice cream sales follow day-ahead solar irradiation forecasts:
    >>> SensorRelationship(Sensor("ice cream sales"), "is_regressed_by", Sensor("solar irradiation"), config={"d": "1D"})

    Polynomial regressive relationships
    -----------------------------------
    x(t)_sensor1 = f( k_1 * ( x(t - d_1)_sensor2 )^p_1 + ... + k_r * ( x(t - d_r)_sensor2 )^p_r )
    where k is an optional scalar (1 by default), d is an optional duration (0 by default),
    p is an optional power (1 by default),
    and r is an implict count of the regressive relationships of sensor1 on sensor2.

    For example, ice cream sales follow the square root of temperature:
    >>> SensorRelationship(Sensor("ice cream sales"), "is_regressed_by", Sensor("temperature"), config={"p": 0.5})

    Cost or utility functions
    -------------------------
    costs = k_1 * x_sensor1 * x_sensor2 + ... + k_r * x_sensor1 * x_sensor_r
    where k is an optional scalar (1 by default),
    and r is an implict count of the scoring relationships of sensor1 on other sensor2.

    For example, retail utility = power * ask price - power * bid price)
    >>> SensorRelationship(Sensor("power"), "is_scored_by", Sensor("ask_price"), config={"k": 1})
    >>> SensorRelationship(Sensor("power"), "is_scored_by", Sensor("bid_price"), config={"k": -1})

    # todo: test the case in which a scheduler wants to do a cost optimisation, while the power sensor also has an emissions scoring relationship
        # where and how do we decide which relationships the scheduler should use?
    """

    relationship_function = db.Column(
        db.Enum(
            "is_sum_of",  # todo: obsolete?
            "is_equal_or_less_than",
            "is",
            "is_equal_or_greater_than",
            "is_product_of",  # todo: obsolete?
            "is_scored_by",
            "is_less_than",
            "is_greater_than",
            "is_regressed_by",  # todo: I don't like the word regression in this context. I prefer is_function_of: see also https://en.wikipedia.org/wiki/Dependent_and_independent_variables#Statistics_synonyms
        ),
        nullable=False,
        primary_key=True,
    )
    config = db.Column(
        mutable_json_type(dbtype=JSONB, nested=True),
        nullable=False,
        default={},
        primary_key=True,
    )  # this makes SQLAlchemy aware of changes at all levels of the JSON field:
    # from https://amercader.net/blog/beware-of-json-fields-in-sqlalchemy/

    sensor1_id = db.Column(
        db.Integer, db.ForeignKey("sensor.id"), nullable=False, primary_key=True
    )
    sensor1 = db.relationship(
        "Sensor",
        foreign_keys=[sensor1_id],
        backref=db.backref("dependent_related_sensors", lazy=True),
    )

    sensor2_id = db.Column(
        db.Integer, db.ForeignKey("sensor.id"), nullable=False, primary_key=True
    )
    sensor2 = db.relationship(
        "Sensor",
        foreign_keys=[sensor2_id],
        backref=db.backref("independent_related_sensors", lazy=True),
    )

    def __init__(
        self,
        sensor1: Sensor,
        relationship_function: str,
        sensor2: Sensor = None,
        d: Union[str, dict, pd.DateOffset] = None,
        k: float = None,
        p: float = None,
        config: dict = None,  # todo: maybe we shouldn't allow setting the config dict directly, because without it is cleaner to have useful validation on individual parameters like d.
    ):
        if sensor2 is None:
            sensor2 = sensor1
        if config is None:
            config = {}
        if d and "d" not in config:
            if isinstance(d, str):
                # d should be a pandas frequency string
                assert isinstance(to_offset(d), pd.DateOffset)
                config["d"] = d
            elif isinstance(d, dict):
                # d should be DateOffset kwargs
                assert isinstance(pd.offsets.DateOffset(**d), pd.DateOffset)
                config["d"] = d
            elif isinstance(d, pd.DateOffset):
                # d should be convertible to a frequency string or DateOffset kwargs (and vice versa)
                config["d"] = date_offset_to_freqstr_or_kwargs(d)
        if k and "k" not in config:
            config["k"] = k
        if p and "p" not in config:
            config["p"] = p
        self.sensor1 = sensor1
        self.relationship_function = relationship_function
        self.sensor2 = sensor2
        self.config = json.dumps(config)

    @property
    def type(
        self,
    ) -> str:  # todo: relationship_type (choose a design pattern and be consistent, also for sensor.sensor_type, process.process_type, process.sensor_type, asset.asset_type, etc.)
        if self.relationship_function in (
            "is",
            "is_less_than",
            "is_greater_than",
            "is_equal_or_less_than",
            "is_equal_or_greater_than",
        ):
            return "constraint"
        # todo: should is_scored_by be of type "score"?
        return "dependency"  # todo: I prefer "dependency" over "function", because an is_regressed_by relationship actually does not specify the function itself, but rather the independent and dependent variables within an unspecified function

    @property
    def offset(self) -> Optional[pd.DateOffset]:
        d: Union[str, dict] = json.loads(self.config).get("d", None)
        if isinstance(d, str):
            # pandas frequency string
            return to_offset(d)
        if isinstance(d, dict):
            # standard date increments like year and years that pandas supports from dateutil.relativedelta
            return pd.offsets.DateOffset(**d)

    def apply_lags(self, dt: pd.Timestamp, lags: List[int]) -> List[pd.Timestamp]:
        """Supports arithmetic within pandas Timestamp limitations,
        a span of approximately 584 years.

        References
        ----------
        Timestamp limitations
            https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#timestamp-limitations
        """
        if self.offset is not None:
            return [dt + lag * self.offset for lag in lags]


class AssetGroupRelationship(db.Model):
    """An asset group relationship defines how assets are grouped.

    asset1 combines a group of assets.
    asset2 belongs to that group.
    """

    id = db.Column(
        db.Integer, primary_key=True
    )  # todo: required? or move primary key to asset1_id and asset2_id

    asset1_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset1 = db.relationship(
        "Asset",
        foreign_keys=[asset1_id],
        backref=db.backref("combines_assets", lazy=True),
    )  # todo: rename combines_assets

    asset2_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    asset2 = db.relationship(
        "Asset",
        foreign_keys=[asset2_id],
        backref=db.backref("belongs_to_assets", lazy=True),
    )  # todo: rename belongs_to_assets


class ProcessMixin:
    start: datetime
    duration: timedelta

    @property
    def end(self) -> datetime:
        return self.start + self.duration


class Process(db.Model, ProcessMixin):
    id = db.Column(db.Integer, primary_key=True)
    start = db.Column(db.DateTime(timezone=True), nullable=False)
    duration = db.Column(db.Interval(), nullable=False)  # todo: or end?
    rate = db.Column(db.Float, nullable=False)
    source_id = db.Column(
        db.Integer, db.ForeignKey(DataSource.__tablename__ + ".id"), primary_key=True
    )
    source = db.relationship(
        "DataSource",
        foreign_keys=[source_id],
        backref=db.backref("processes", lazy=True),
    )

    sensor_id = db.Column(db.Integer, db.ForeignKey("sensor.id"), nullable=False)
    sensor = db.relationship(
        "Sensor", foreign_keys=[sensor_id], backref=db.backref("processes", lazy=True)
    )

    @property
    def process_type(self):
        """A process type defines what type of data a process describes, and includes a unit.

        Examples of process types: water consumption, electricity consumption, gas consumption.

        Processes of the same type can be aggregated.
        Processes of different types can be generalized.
        """
        return self.sensor.sensor_type


class AggregatedProcess(ProcessMixin):
    """A process that consists of sub-processes of the same type.

    For example, an hourly household water consumption process consists of
    two 1-minute water consumption processes of a coffee machine and a toilet.

    Notice the aggregation over both time and assets:
    - time: the 2 minutes occur within the hour
    - assets: the household groups the coffee machine and toilet

    References
    ----------
    John Miles Smith and Diane CP Smith. Database abstractions: aggregation and generalization
        in ACM Transactions on Database Systems (TODS), Volume 2, No. 2, pages 105-133, 1977.
        https://dl.acm.org/doi/abs/10.1145/320544.320546
    """

    processes: List[Process]

    @property
    def start(self) -> datetime:
        return (
            min(process.start for process in self.processes) if self.processes else None
        )

    @property
    def duration(self) -> timedelta:
        return (
            max(process.end for process in self.processes) - self.start
            if self.processes
            else None
        )

    @property
    def unit(self) -> str:
        """Returns the unique unit of the component process, if any."""
        combines_units = list(set(process.unit for process in self.processes))
        assert len(combines_units) <= 1
        return combines_units[0] if combines_units else None

    @property
    def type(self) -> "SensorType":
        """Returns the unique type of the component process, if any."""
        combines_types = list(set(process.process_type for process in self.processes))
        assert len(combines_types) <= 1
        return combines_types[0] if combines_types else None


class GeneralizedProcess(ProcessMixin):
    """A process that consists of sub-processes from different categories.

    For example, a coffee machine making a cup of coffee consists of
    a water consumption process and an electricity consumption process.

    References
    ----------
    John Miles Smith and Diane CP Smith. Database abstractions: aggregation and generalization
        in ACM Transactions on Database Systems (TODS), Volume 2, No. 2, pages 105-133, 1977.
        https://dl.acm.org/doi/abs/10.1145/320544.320546
    """

    processes: List[Process]

    @property
    def start(self) -> datetime:
        return (
            min(process.start for process in self.processes) if self.processes else None
        )

    @property
    def duration(self) -> timedelta:
        return (
            max(process.end for process in self.processes) - self.start
            if self.processes
            else None
        )


class ProcessLabel(db.Model):
    """Just for labelling similar processes, e.g. in non-exclusive categories."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    hover_label = db.Column(db.String(80), nullable=True, unique=False)


class ProcessLabelRelationship(db.Model):
    """A process label relationship assigns process labels to processes."""

    process_id = db.Column(
        db.Integer, db.ForeignKey("process.id"), nullable=False, primary_key=True
    )
    process = db.relationship(
        "Process",
        foreign_keys=[process_id],
        backref=db.backref("labels", lazy=True),
    )
    process_label_id = db.Column(
        db.Integer, db.ForeignKey("process_label.id"), nullable=False, primary_key=True
    )
    process_label = db.relationship(
        "ProcessLabel",
        foreign_keys=[process_label_id],
        backref=db.backref("processes", lazy=True),
    )


class Seasonality(db.Model):
    """Also known as periodicity, seasonality defines the recurrent nature of asset activity.

    Some examples: *

    - annually (calendar year is 365 or 366 days depending on leap year): Seasonality(n=1, freq_str="years")
    - daily (calendar day is 23, 24 or 25 hours depending on DST): Seasonality(n=1, freq_str="days")
    - 24 hours: Seasonality(n=24, freq_str="hours")
    - 1 business day: Seasonality(n=1, freq_str="BDay")
    - 4th of the current month: Seasonality(n=4, freq_str="day") **

    Note that for non-existing datetimes, pandas DateOffsets will roll forward or backward.
    For example:
    >>> pd.Timestamp("2020-3-30") - 1 * pd.DateOffset(day=30, months=1)
    Timestamp('2020-02-29 00:00:00')

    * Be careful with the difference between singular and plural frequency strings.
      The standard date increments like year and years stem from dateutil.relativedelta definitions.

    ** Currently we do not support persisting combinations such as "the 4th of the month".
       This would require storing two kwargs to persist DateOffset(day=4, months=1).
       Once stored, the arithmetic would behave as expected:
       >>> pd.Timestamp("2020-5-10") + 2 * pd.DateOffset(day=4, months=1)
       Timestamp('2020-07-04 00:00:00')

    References
    ----------
    pandas frequency strings
        https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#offset-aliases
    dateutil relativedelta arguments
        https://dateutil.readthedocs.io/en/stable/relativedelta.html
    """

    id = db.Column(db.Integer, primary_key=True)
    n = db.Column(db.Integer)
    freq_str = db.Column(
        db.Enum(*STANDARD_OFFSET_NAMES, *NON_STANDARD_OFFSET_NAMES),
        nullable=False,
    )

    @property
    def offset(self) -> pd.DateOffset:

        # standard date increments like year and years that pandas supports from dateutil.relativedelta
        if self.freq_str in STANDARD_OFFSET_NAMES:
            return pd.offsets.DateOffset(**{self.freq_str: self.n})

        # non-standard date increments like BDay and YearEnd that pandas supports in addition
        mapping = {
            offset.__name__: offset._prefix
            for offset in [
                getattr(pd.tseries.offsets, name) for name in NON_STANDARD_OFFSET_NAMES
            ]
            if isinstance(offset._prefix, str)
        }
        return to_offset(str(self.n) + mapping[self.freq_str])

    def apply_lags(self, dt: pd.Timestamp, lags: List[int]) -> List[pd.Timestamp]:
        """Supports arithmetic within pandas Timestamp limitations,
        a span of approximately 584 years.

        References
        ----------
        Timestamp limitations
            https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#timestamp-limitations
        """
        return [dt + lag * self.offset for lag in lags]


def date_offset_to_freqstr_or_kwargs(d: pd.DateOffset) -> Union[str, dict]:
    """d is converted to a frequency string or DateOffset kwargs.
    We also check whether we can revert back to a pandas DateOffset,
    and raise an AssertionError if reverting fails.
    """
    try:
        d_str: str = d.freqstr
        assert to_offset(d_str) == d
        return d_str
    except ValueError:
        d_dict: dict = d.kwds
        assert pd.offsets.DateOffset(**d_dict) == d
        return d_dict


def test_date_offset_logic():
    d_dict = {"months": 1, "day": 4}
    assert date_offset_to_freqstr_or_kwargs(pd.offsets.DateOffset(**d_dict)) == d_dict
    d_str = "15B"
    assert date_offset_to_freqstr_or_kwargs(to_offset(d_str)) == d_str


def test_seasonality():
    """Test leap year."""
    s = Seasonality(n=1, freq_str="years")
    lagged_datetimes = s.apply_lags(dt=pd.Timestamp("2020-10-10"), lags=[1])
    assert lagged_datetimes[0] == pd.Timestamp("2021-10-10")


class SensorSeasonalityRelationship(db.Model):
    sensor_id = db.Column(
        db.Integer(), db.ForeignKey("sensor.id"), primary_key=True, nullable=False
    )
    seasonality_id = db.Column(
        db.Integer(), db.ForeignKey("seasonality.id"), primary_key=True, nullable=False
    )

    sensor = db.relationship(
        "Sensor",
        foreign_keys=[sensor_id],
        backref=db.backref("seasonalities", lazy=True),
    )
    seasonality = db.relationship(
        "Seasonality",
        foreign_keys=[seasonality_id],
        backref=db.backref("sensors", lazy=True),
    )


class Actuator(db.Model):
    """An actuator defines a type of action that can be taken on an asset.

    Action type, action and version are useful to structure the file system:
    - action types are modules
    - actions are submodules
    - versions are functions)
    Action types are also useful as filters for the API (and UI).
    """

    id = db.Column(db.Integer, primary_key=True)

    # The type of action (e.g. posting, forecasting or scheduling)
    action_type = db.Column(
        db.Enum(
            "posting",
            "forecasting",
            "scheduling",
            "decomposing",
        ),
        nullable=False,
    )
    action = db.Column(
        db.Enum(
            "can_shift",
            "can_curtail",
        ),
        nullable=False,
        primary_key=True,
    )
    version = db.Column(
        db.String(80), default="0.0.0"
    )  # todo: discuss integer vs. semantic versioning

    @staticmethod
    def trigger(self, **kwargs):
        """Call the function associated with this actuator."""
        return

    @property
    def endpoint(self):
        """Return the API endpoint for this actuator, which can be used to trigger the actuator."""
        return


class AssetActuatorRelationship(db.Model):
    asset_id = db.Column(
        db.Integer, db.ForeignKey("asset.id"), nullable=False, primary_key=True
    )
    asset = db.relationship(
        "Asset",
        foreign_keys=[asset_id],
        backref=db.backref("actuators", lazy=True),
    )

    actuator_id = db.Column(db.Integer, db.ForeignKey("actuator.id"), nullable=False)
    actuator = db.relationship(
        "Actuator",
        foreign_keys=[actuator_id],
        backref=db.backref("assets", lazy=True),
    )


class Belief(db.Model, tb.TimedBeliefDBMixin):
    """The basic description of a data point as a belief.

    From timely_beliefs.TimedBelief documentation, this includes the following:
        - a sensor (what the belief is about)
        - an event (an instant or period of time that the belief is about)
        - a horizon (indicating when the belief was formed with respect to the event)
        - a source (who or what formed the belief)
        - a value (what was believed)
        - a cumulative probability (the likelihood of the value being equal or lower than stated)*

        * The default assumption is that the mean value is given (cp=0.5), but if no beliefs about possible other outcomes
        are given, then this will be treated as a deterministic belief (cp=1). As an alternative to specifying an cumulative
        probability explicitly, you can specify an integer number of standard deviations which is translated
        into a cumulative probability assuming a normal distribution (e.g. sigma=-1 becomes cp=0.1587).
    """

    sensor_id = db.Column(
        db.Integer(), db.ForeignKey("sensor.id", ondelete="CASCADE"), primary_key=True
    )
    sensor = db.relationship(
        "Sensor", foreign_keys=[sensor_id], backref=db.backref("beliefs", lazy=True)
    )
    source_id = db.Column(
        db.Integer, db.ForeignKey(DataSource.__tablename__ + ".id"), primary_key=True
    )
    source = db.relationship(
        "DataSource", foreign_keys=[source_id], backref=db.backref("beliefs", lazy=True)
    )


class Annotation(db.Model):
    """An annotation is a label that applies to a specific time or time span.

    Examples of annotation types:
        - user annotation: annotation.type == "annotation" and annotation.source.type == "user"
        - unresolved alert: annotation.type == "alert"
        - resolved alert: annotation.type == "annotation" and annotation.source.type == "alerting script"
        - organisation holiday: annotation.type == "holiday" and annotation.source.type == "user"
        - national, school or bank holiday: annotation.type == "holiday" and annotation.source.type == "holiday script"
    """

    id = db.Column(db.Integer, nullable=False, primary_key=True)
    name = db.Column(db.String(80), nullable=False)  # todo: 80?
    start = db.Column(db.DateTime(timezone=True), nullable=False)
    duration = db.Column(db.Interval(), default=timedelta(0), nullable=False)
    source_id = db.Column(
        db.Integer, db.ForeignKey(DataSource.__tablename__ + ".id"), primary_key=True
    )
    source = db.relationship(
        "DataSource",
        foreign_keys=[source_id],
        backref=db.backref("annotations", lazy=True),
    )
    type = db.Column(db.Enum("alert", "holiday", "annotation"))

    @property
    def end(self) -> datetime:
        return self.start + self.duration


class AssetAnnotationRelationship(db.Model):
    asset_id = db.Column(
        db.Integer, db.ForeignKey("asset.id"), nullable=False, primary_key=True
    )
    asset = db.relationship(
        "Asset",
        foreign_keys=[asset_id],
        backref=db.backref("annotations", lazy=True),
    )

    annotation_id = db.Column(
        db.Integer, db.ForeignKey("annotation.id"), nullable=False
    )
    annotation = db.relationship(
        "Annotation",
        foreign_keys=[annotation_id],
        backref=db.backref("assets", lazy=True),
    )
