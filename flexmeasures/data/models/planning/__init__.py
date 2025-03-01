from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Type, Union

import pandas as pd
from flask import current_app

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset as Asset
from flexmeasures.utils.coding_utils import deprecated
from .exceptions import WrongEntityException


# todo: Use | instead of Union, list instead of List and dict instead of Dict when FM stops supporting Python 3.9 (because of https://github.com/python/cpython/issues/86399)
SchedulerOutputType = Union[pd.Series, List[Dict[str, Any]], None]


class Scheduler:
    """
    Superclass for all FlexMeasures Schedulers.

    A scheduler currently computes the schedule for one flexible asset.
    TODO: extend to multiple flexible assets.

    The scheduler knows the power sensor of the flexible asset.
    It also knows the basic timing parameter of the schedule (start, end, resolution), including the point in time when
    knowledge can be assumed to be available (belief_time).

    Furthermore, the scheduler needs to have knowledge about the asset's flexibility model (under what constraints
    can the schedule be optimized?) and the system's flexibility context (which other sensors are relevant, e.g. prices).
    These two flexibility configurations are usually fed in from outside, so the scheduler should check them.
    The deserialize_flex_config function can be used for that.

    """

    __version__ = None
    __author__ = None

    sensor: Sensor | None = None
    asset: Asset | None = None

    start: datetime
    end: datetime
    resolution: timedelta
    belief_time: datetime

    round_to_decimals: int

    flex_model: dict | None = None
    flex_context: dict | None = None

    fallback_scheduler_class: "Type[Scheduler] | None" = None
    info: dict | None = None

    config_deserialized = False  # This flag allows you to let the scheduler skip checking config, like timing, flex_model and flex_context

    # set to True if the Scheduler supports triggering on an Asset or False
    # if the Scheduler expects a Sensor
    supports_scheduling_an_asset = False

    return_multiple: bool = False

    def __init__(
        self,
        sensor: Sensor | None = None,  # deprecated
        start: datetime | None = None,
        end: datetime | None = None,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
        asset_or_sensor: Asset | Sensor | None = None,
        round_to_decimals: int | None = 6,
        flex_model: dict | None = None,
        flex_context: dict | None = None,
        return_multiple: bool = False,
    ):
        """
        Initialize a new Scheduler.

        TODO: We might adapt the class design, so that a Scheduler object is initialized with configuration parameters,
              and can then be used multiple times (via compute()) to compute schedules of different kinds, e.g.
                If we started later (put in a later start), what would the schedule be?
                If we could change set points less often (put in a coarser resolution), what would the schedule be?
                If we knew what was going to happen (put in a later belief_time), what would the schedule have been?
              For now, we don't see the best separation between config and state parameters (esp. within flex models)
              E.g. start and flex_model[soc_at_start] are intertwined.
        """

        if sensor is not None:
            current_app.logger.warning(
                "The `sensor` keyword argument is deprecated. Please, consider using the argument `asset_or_sensor`."
            )
            asset_or_sensor = sensor

        if self.supports_scheduling_an_asset and isinstance(asset_or_sensor, Sensor):
            raise WrongEntityException(
                f"The scheduler class {self.__class__.__name__} expects an Asset object but a Sensor was provided."
            )

        self.sensor = None
        self.asset = None

        if isinstance(asset_or_sensor, Sensor):
            self.sensor = asset_or_sensor
        elif isinstance(asset_or_sensor, Asset):
            self.asset = asset_or_sensor
        else:
            raise WrongEntityException(
                f"The scheduler class {self.__class__.__name__} expects an Asset or Sensor objects but an object of class `{asset_or_sensor.__class__.__name__}` was provided."
            )

        self.start = start
        self.end = end
        self.resolution = resolution
        self.belief_time = belief_time
        self.round_to_decimals = round_to_decimals
        if flex_model is None:
            flex_model = {}
        self.flex_model = flex_model
        if flex_context is None:
            flex_context = {}
        self.flex_context = flex_context

        if self.info is None:
            self.info = dict(scheduler=self.__class__.__name__)

        self.return_multiple = return_multiple

    def compute_schedule(self) -> pd.Series | None:
        """
        Overwrite with the actual computation of your schedule.

        Deprecated method in v0.14. As an alternative, use Scheduler.compute().
        """
        return self.compute()

    def compute(self) -> SchedulerOutputType:
        """
        Overwrite with the actual computation of your schedule.
        """

        return None

    @classmethod
    def get_data_source_info(cls: type) -> dict:
        """
        Create and return the data source info, from which a data source lookup/creation is possible.
        See for instance get_data_source_for_job().
        """
        source_info = dict(
            model=cls.__name__, version="1", name="Unknown author"
        )  # default

        if hasattr(cls, "__version__"):
            source_info["version"] = str(cls.__version__)
        else:
            current_app.logger.warning(
                f"Scheduler {cls.__name__} loaded, but has no __version__ attribute."
            )
        if hasattr(cls, "__author__"):
            source_info["name"] = str(cls.__author__)
        else:
            current_app.logger.warning(
                f"Scheduler {cls.__name__} has no __author__ attribute."
            )
        return source_info

    def persist_flex_model(self):
        """
        If useful, (parts of) the flex model can be persisted here,
        e.g. as asset attributes, sensor attributes or as sensor data (beliefs).
        """
        pass

    def deserialize_config(self):
        """
        Check all configurations we have, throwing either ValidationErrors or ValueErrors.
        Other code can decide if/how to handle those.
        """
        self.deserialize_timing_config()
        self.deserialize_flex_config()
        self.config_deserialized = True

    def deserialize_timing_config(self):
        """
        Check if the timing of the schedule is valid.
        Raises ValueErrors.
        """
        if self.start > self.end:
            raise ValueError(f"Start {self.start} cannot be after end {self.end}.")
        # TODO: check if resolution times X fits into schedule length
        # TODO: check if scheduled events would start "on the clock" w.r.t. resolution (see GH#10)

    def deserialize_flex_config(self):
        """
        Check if the flex model and flex context are valid. Should be overwritten.

        Ideas:
        - Apply a schema to check validity (see in-built flex model schemas)
        - Check for inconsistencies between settings (can also happen in Marshmallow)
        - fill in missing values from the scheduler's knowledge (e.g. sensor attributes)

        Raises ValidationErrors or ValueErrors.
        """
        pass


@dataclass
class Commitment:
    """Contractual commitment specifying prices for deviating from a given position.
    ::
    Parameters
    ----------
    name:
        Name of the commitment.
    index:
        Pandas DatetimeIndex defining the time slots to which the commitment applies.
        The index is shared by the group, quantity. upwards_deviation_price and downwards_deviation_price Pandas Series.
    _type:
        'any' or 'each'. Any deviation is penalized via 1 group, whereas each deviation is penalized via n groups.
    group:
        Each time slot is assigned to a group. Deviations are determined for each group.
        The deviation of a group is determined by the time slot with the maximum deviation within that group.
    quantity:
        The deviation for each group is determined with respect to this quantity.
        Can be initialized with a constant value, but always returns a Pandas Series (see also the `index` parameter).
    upwards_deviation_price:
        The deviation in the upwards direction is priced against this price. Use a positive price to set a penalty.
        Can be initialized with a constant value, but always returns a Pandas Series (see also the `index` parameter).
    downwards_deviation_price:
        The deviation in the downwards direction is priced against this price. Use a negative price to set a penalty.
        Can be initialized with a constant value, but always returns a Pandas Series (see also the `index` parameter).
    """

    name: str
    index: pd.DatetimeIndex = field(repr=False, default=None)
    _type: str = field(repr=False, default="each")
    group: pd.Series = field(init=False)
    quantity: pd.Series = 0
    upwards_deviation_price: pd.Series = 0
    downwards_deviation_price: pd.Series = 0

    def __post_init__(self):
        # Try to set the time series index for the commitment
        if self.index is None:
            if isinstance(self.quantity, pd.Series) and isinstance(
                self.quantity.index, pd.DatetimeIndex
            ):
                self.index = self.quantity.index
            elif isinstance(self.upwards_deviation_price, pd.Series) and isinstance(
                self.upwards_deviation_price.index, pd.DatetimeIndex
            ):
                self.index = self.upwards_deviation_price.index
            elif isinstance(self.downwards_deviation_price, pd.Series) and isinstance(
                self.downwards_deviation_price.index, pd.DatetimeIndex
            ):
                self.index = self.downwards_deviation_price.index
            else:
                raise ValueError(
                    "Commitment must be initialized with a pd.DatetimeIndex. Hint: use the `index` argument."
                )

        # Force type conversion of repr fields to pd.Series
        if not isinstance(self.quantity, pd.Series):
            self.quantity = pd.Series(self.quantity, index=self.index)
        if not isinstance(self.upwards_deviation_price, pd.Series):
            self.upwards_deviation_price = pd.Series(
                self.upwards_deviation_price,
                index=self.index,
            )
        if not isinstance(self.downwards_deviation_price, pd.Series):
            self.downwards_deviation_price = pd.Series(
                self.downwards_deviation_price,
                index=self.index,
            )
        if self._type == "any":
            # add all time steps to the same group
            self.group = pd.Series(0, index=self.index)
        elif self._type == "each":
            # add each time step to their own group
            self.group = pd.Series(list(range(len(self.index))), index=self.index)
        else:
            raise ValueError('Commitment `_type` must be "any" or "each".')

        # Name the Series as expected by our device scheduler
        self.quantity = self.quantity.rename("quantity")
        self.upwards_deviation_price = self.upwards_deviation_price.rename(
            "upwards deviation price"
        )
        self.downwards_deviation_price = self.downwards_deviation_price.rename(
            "downwards deviation price"
        )
        self.group = self.group.rename("group")

    def to_frame(self) -> pd.DataFrame:
        """Contains all info apart from the name."""
        return pd.concat(
            [
                self.quantity,
                self.upwards_deviation_price,
                self.downwards_deviation_price,
                self.group,
            ],
            axis=1,
        )


"""
Deprecations
"""

Scheduler.compute_schedule = deprecated(Scheduler.compute, "0.14")(
    Scheduler.compute_schedule
)
