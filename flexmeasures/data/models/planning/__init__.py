from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from flexmeasures import Sensor


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
    The check_flexibility_config function can be used for that.

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

    config_inspected = False  # This flag allows you to let the scheduler skip checking config, like timing, flex_model and flex_context

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
        Overwrite for the actual computation of your schedule.
        """
        return None

    def persist_flex_model(self):
        """If useful, (parts of) the flex model can be persisted (e.g on the sensor) here."""
        pass

    def inspect_config(self):
        self.inspect_timing_config()
        self.inspect_flex_config()
        self.config_inspected = True

    def inspect_timing_config(self):
        """
        Check if the timing of the schedule is valid.
        """
        if self.start > self.end:
            raise ValueError(f"Start {self.start} cannot be after end {self.end}.")
        # TODO: check if resolution times X fits into schedule length
        # TODO: check if scheduled events would start "on the clock" w.r.t. resolution (see GH#10)

    def inspect_flex_config(self):
        """
        Check if the flex model and context are valid. Should be overwritten.

        Ideas:
        - Apply a schema to check validity (see in-built flex model schemas)
        - Check for inconsistencies between settings (can also happen in Marshmallow
        - fill in missing values from the scheduler's knowledge (e.g. sensor attributes)

        Raise ValidationErrors or ValueErrors. Other code can decide if/how to handle those.
        """
        pass
