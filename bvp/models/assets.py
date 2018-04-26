from typing import Dict, Tuple
from random import random

import pandas as pd
import inflection
from inflection import pluralize, titleize

from bvp.database import db


# Give the inflection module some help for our domain
inflection.UNCOUNTABLES.add("solar")
inflection.UNCOUNTABLES.add("wind")


def random_jeju_island_location() -> Tuple[float, float]:
    """ Temporary helper for randomizing locations of assets on the island
    (for which we have no real location). TODO: make obsolete? """
    return 33.3 + random() * 0.2, 126.25 + random() * .65


def get_capacity_for(asset_name: str, asset_type_name: str) -> float:
    """Temporary helper to guess a maximum capacity from the data we have"""
    if asset_type_name in ("ev", "building"):
        return -1 * min(pd.read_pickle("data/pickles/df_%s_res15T.pickle" % asset_name).y)
    else:
        return max(pd.read_pickle("data/pickles/df_%s_res15T.pickle" % asset_name).y)


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
            yearly_seasonality=self.yearly_seasonality
        )

    @property
    def pluralized_name(self):
        return pluralize(self.name)

    def __repr__(self):
        return '<AssetType %r>' % self.name


class Asset(db.Model):
    """Each asset is an energy- consuming or producing hardware. """

    id = db.Column(db.Integer, primary_key=True)
    # The name
    name = db.Column(db.String(80), default="", unique=True)
    # The name we want to see
    display_name = db.Column(db.String(80), default="", unique=True)
    # The name of the assorted AssetType
    asset_type_name = db.Column(db.String(80), db.ForeignKey('asset_type.name'), nullable=False)
    # How many MW at peak usage
    capacity_in_mw = db.Column(db.Float, nullable=False)
    # latitude is the North/South coordinate
    latitude = db.Column(db.Float, nullable=False)
    # longitude is the East/West coordinate
    longitude = db.Column(db.Float, nullable=False)
    # owner
    owner_id = db.Column(db.Integer, db.ForeignKey('bvp_users.id'))


    def __init__(self, **kwargs):
        super(Asset, self).__init__(**kwargs)
        self.name = self.name.replace(" (MW)", "")
        if self.display_name == "":
            self.display_name = titleize(self.name)

    asset_type = db.relationship('AssetType', backref=db.backref('assets', lazy=True))
    owner = db.relationship('User', backref=db.backref('assets', lazy=True))

    @property
    def asset_type_display_name(self) -> str:
        return titleize(self.asset_type_name)

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

    def to_dict(self) -> Dict[str, str]:  # TODO: actually not always a str
        return dict(name=self.name,
                    display_name=self.display_name,
                    asset_type_name=self.asset_type_name,
                    latitude=self.latitude,
                    longitude=self.longitude,
                    capacity_in_mw=self.capacity_in_mw)

    def __repr__(self):
        return '<Asset %r (%s)>' % (self.name, self.asset_type_name)
