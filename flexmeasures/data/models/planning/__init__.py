from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from flask import current_app

from flexmeasures.data.models.time_series import Sensor


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

    sensor: Sensor
    start: datetime
    end: datetime
    resolution: timedelta
    belief_time: datetime
    round_to_decimals: int
    flex_model: Optional[dict] = None
    flex_context: Optional[dict] = None

    config_deserialized = False  # This flag allows you to let the scheduler skip checking config, like timing, flex_model and flex_context

    def __init__(
        self,
        sensor,
        start,
        end,
        resolution,
        belief_time: Optional[datetime] = None,
        round_to_decimals: Optional[int] = 6,
        flex_model: Optional[dict] = None,
        flex_context: Optional[dict] = None,
    ):
        """
        Initialize a new Scheduler.

        TODO: We might adapt the class design, so that A Scheduler object is initialized with configuration parameters,
              and can then be used multiple times (via compute_schedule()) to compute schedules of different kinds, e.g.
                If we started later (put in a later start), what would the schedule be?
                If we could change set points less often (put in a coarser resolution), what would the schedule be?
                If we knew what was going to happen (put in a later belief_time), what would the schedule have been?
              For now, we don't see the best separation between config and state parameters (esp. within flex models)
              E.g. start and flex_model[soc_at_start] are intertwined.
        """
        self.sensor = sensor
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

    def compute_schedule(self) -> Optional[pd.Series]:
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
        If useful, (parts of) the flex model can be persisted (e.g. on the sensor) here,
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
