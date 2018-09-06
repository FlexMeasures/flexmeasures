from typing import Dict, List, Tuple, Union
from datetime import datetime, timedelta

import isodate
import inflection
from inflection import pluralize, titleize
from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.time_series import TimedValue
from bvp.utils.config_utils import get_naming_authority, get_addressing_scheme


# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.add("solar")
inflection.UNCOUNTABLES.add("wind")


class AssetType(db.Model):
    """Describing asset types for our purposes"""

    name = db.Column(db.String(80), primary_key=True)
    is_consumer = db.Column(db.Boolean(), nullable=False, default=False)
    is_producer = db.Column(db.Boolean(), nullable=False, default=False)
    can_curtail = db.Column(db.Boolean(), nullable=False, default=False, index=True)
    can_shift = db.Column(db.Boolean(), nullable=False, default=False, index=True)
    daily_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    weekly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)
    yearly_seasonality = db.Column(db.Boolean(), nullable=False, default=False)

    @property
    def preconditions(self) -> Dict[str, bool]:
        """Assumptions about the time series data set, such as normality and stationarity
        For now, this is usable input for Prophet (see init), but it might evolve or go away."""
        return dict(
            daily_seasonality=self.daily_seasonality,
            weekly_seasonality=self.weekly_seasonality,
            yearly_seasonality=self.yearly_seasonality,
        )

    @property
    def weather_correlations(self) -> List[str]:
        """Known correlations of weather sensor type and asset type."""
        correlations = []
        if self.name == "solar":
            correlations.append("radiation")
        if self.name == "wind":
            correlations.append("wind_speed")
        if self.name in ("charging_station", "battery", "building"):
            correlations.append("temperature")
        return correlations

    @property
    def pluralized_name(self):
        return pluralize(self.name)

    def __repr__(self):
        return "<AssetType %r>" % self.name


class Asset(db.Model):
    """Each asset is an energy- consuming or producing hardware. """

    id = db.Column(db.Integer, primary_key=True)
    # The name
    name = db.Column(db.String(80), default="", unique=True)
    # The name we want to see
    display_name = db.Column(db.String(80), default="", unique=True)
    # The name of the assorted AssetType
    asset_type_name = db.Column(
        db.String(80), db.ForeignKey("asset_type.name"), nullable=False
    )
    # How many MW at peak usage
    capacity_in_mw = db.Column(db.Float, nullable=False)
    # latitude is the North/South coordinate
    latitude = db.Column(db.Float, nullable=False)
    # longitude is the East/West coordinate
    longitude = db.Column(db.Float, nullable=False)
    # owner
    owner_id = db.Column(db.Integer, db.ForeignKey("bvp_users.id", ondelete="CASCADE"))

    def __init__(self, **kwargs):
        super(Asset, self).__init__(**kwargs)
        self.name = self.name.replace(" (MW)", "")
        if self.display_name == "" or self.display_name is None:
            self.display_name = titleize(self.name)

    asset_type = db.relationship("AssetType", backref=db.backref("assets", lazy=True))
    owner = db.relationship(
        "User",
        backref=db.backref(
            "assets", lazy=True, cascade="all, delete-orphan", passive_deletes=True
        ),
    )

    @property
    def asset_type_display_name(self) -> str:
        return titleize(self.asset_type_name)

    @property
    def entity_address(self) -> str:
        return "%s.%s:%s:%s" % (
            get_addressing_scheme(),
            get_naming_authority(),
            self.owner_id,
            self.id,
        )

    @property
    def location(self) -> Tuple[float, float]:
        return self.latitude, self.longitude

    def capacity_factor_in_percent_for(self, load_in_mw) -> int:
        if self.capacity_in_mw == 0:
            return 0
        return min(round((load_in_mw / self.capacity_in_mw) * 100, 2), 100)

    @property
    def is_pure_consumer(self) -> bool:
        """Return True if this asset is consuming but not producing."""
        return self.asset_type.is_consumer and not self.asset_type.is_producer

    @property
    def is_pure_producer(self) -> bool:
        """Return True if this asset is producing but not consuming."""
        return self.asset_type.is_producer and not self.asset_type.is_consumer

    def to_dict(self) -> Dict[str, Union[str, float]]:
        return dict(
            name=self.name,
            display_name=self.display_name,
            asset_type_name=self.asset_type_name,
            latitude=self.latitude,
            longitude=self.longitude,
            capacity_in_mw=self.capacity_in_mw,
        )

    def __repr__(self):
        return "<Asset %d:%r (%s)>" % (self.id, self.name, self.asset_type_name)


class Power(TimedValue, db.Model):
    """
    All measurements of power data are stored in one slim table.
    TODO: datetime objects take up most of the space (12 bytes each)). One way out is to normalise them out to a table.
    TODO: If there are more than one measurement per asset per time step possible, we can expand rather easily.
    """

    asset_id = db.Column(
        db.Integer(), db.ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True
    )
    asset = db.relationship(
        "Asset",
        backref=db.backref(
            "measurements",
            lazy=True,
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    @classmethod
    def make_query(
        cls,
        asset_name: str,
        query_window: Tuple[datetime, datetime],
        horizon_window: Tuple[Union[None, timedelta], Union[None, timedelta]] = (
            None,
            None,
        ),
        rolling: bool = True,
        source_ids: Union[int, List[int]] = None,
        session: Session = None,
    ) -> Query:
        if session is None:
            session = db.session
        start, end = query_window
        # Todo: get data resolution for the asset
        resolution = timedelta(minutes=15)
        q_start = (
            start - resolution
        )  # Adjust for the fact that we index time slots by their start time
        query = (
            session.query(Power.datetime, Power.value, Power.horizon, DataSource.label)
            .join(DataSource)
            .filter(Power.data_source_id == DataSource.id)
            .join(Asset)
            .filter(Asset.name == asset_name)
            .filter((Power.datetime > q_start) & (Power.datetime < end))
        )
        # TODO: this could probably become a util function which we can re-use in all make_query functions
        if source_ids is not None and not isinstance(source_ids, list):
            source_ids = [source_ids]  # ensure source_ids is a list
        if source_ids:
            # Collect only data from sources that are either a specified user id or a script
            script_sources = DataSource.query.filter(DataSource.type == "script").all()
            user_sources = (
                DataSource.query.filter(DataSource.type == "user")
                .filter(DataSource.id.in_(source_ids))
                .all()
            )
            script_source_ids = [script_source.id for script_source in script_sources]
            user_source_ids = [user_source.id for user_source in user_sources]
            query = query.filter(
                Power.data_source_id.in_(user_source_ids)
                | Power.data_source_id.in_(script_source_ids)
            )
        # TODO: this should become a util function which we can re-use in all
        #       make_query functions to add the horizon filter
        short_horizon, long_horizon = horizon_window
        if (
            short_horizon is not None
            and long_horizon is not None
            and short_horizon == long_horizon
        ):
            if rolling:
                query = query.filter(Power.horizon == short_horizon)
            else:  # Deduct the difference in end times of the timeslot and the query window
                query = query.filter(
                    Power.horizon
                    == short_horizon - (end - (Power.datetime + resolution))
                )
        else:
            if short_horizon is not None:
                if rolling:
                    query = query.filter(Power.horizon >= short_horizon)
                else:
                    query = query.filter(
                        Power.horizon
                        >= short_horizon - (end - (Power.datetime + resolution))
                    )
            if long_horizon is not None:
                if rolling:
                    query = query.filter(Power.horizon <= long_horizon)
                else:
                    query = query.filter(
                        Power.horizon
                        <= long_horizon - (end - (Power.datetime + resolution))
                    )
        return query

    def to_dict(self):
        return {
            "datetime": isodate.datetime_isoformat(self.datetime),
            "asset_id": self.asset_id,
            "value": self.value,
            "horizon": self.horizon,
        }

    def __init__(self, **kwargs):
        super(Power, self).__init__(**kwargs)

    def __repr__(self):
        return "<Power %.2f on Asset %s at %s by DataSource %s, horizon %s>" % (
            self.value,
            self.asset_id,
            self.datetime,
            self.data_source_id,
            self.horizon,
        )
