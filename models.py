from collections import namedtuple
from typing import Dict


# Time resolutions
resolutions = ["15T", "1h", "1d", "1w"]

# The confidence interval for forecasting
confidence_interval_width = .9


class Asset:
    """Each asset is a consuming or producing hardware.
    This class should only contain simple types, so it is easy to load/dump to Json."""

    # the name of the assorted AssetType
    asset_type_name: str
    # not used yet
    area_code: str

    def __init__(self, name: str, asset_type_name=None, area_code=""):
        self.orig_name = name
        self.asset_type_name = asset_type_name
        self.area_code = area_code

    @property
    def name(self) -> str:
        """The name we actually want to use"""
        repr_name = self.orig_name
        if self.asset_type_name == "solar":
            repr_name = repr_name.replace(" (MW)", "")
        return repr_name.replace(" ", "_").lower()

    @name.setter
    def name(self, new_name):
        self.name = new_name

    def to_dict(self) -> Dict[str, str]:
        return dict(name=self.name, asset_type_name=self.asset_type_name, area_code=self.area_code)


# queries reference attributes from Asset to enable grouping and querying them
AssetQuery = namedtuple('AssetQuery', 'attr val')


# an asset group is defined by OR-linked asset queries
asset_groups = dict(
        solar=(AssetQuery(attr="asset_type_name", val="solar"),),
        wind=(AssetQuery(attr="asset_type_name", val="wind"),),
        renewables=(AssetQuery(attr="asset_type_name", val="solar"),
                    AssetQuery(attr="asset_type_name", val="wind")),
        vehicles=(AssetQuery(attr="asset_type_name", val="ev"),)
    )


class AssetType:
    """Describing asset types for our purposes"""

    name: str = None

    # Assumptions about the time series data set, such as normality and stationarity
    # For now, this is usable input for Prophet (see init), but it might evolve.
    preconditions = Dict[str, bool]

    def __init__(self, name: str,
                 daily_seasonality: bool=False, weekly_seasonality: bool=False, yearly_seasonality: bool=False):
        self.name = name

        self.preconditions = dict(
            daily_seasonality=daily_seasonality,
            weekly_seasonality=weekly_seasonality,
            yearly_seasonality=yearly_seasonality
        )


asset_types = dict(
    solar=AssetType("solar", daily_seasonality=True, yearly_seasonality=True),
    wind=AssetType("wind", daily_seasonality=True, yearly_seasonality=True)
)
