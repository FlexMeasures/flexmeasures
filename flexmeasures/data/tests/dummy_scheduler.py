from datetime import datetime, timedelta

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning import Scheduler
from flexmeasures.data.models.planning.utils import initialize_series


class DummyScheduler(Scheduler):

    __author__ = "Test Organization"
    __version__ = "3"

    def schedule(
        self,
        sensor: Sensor,
        start: datetime,
        end: datetime,
        resolution: timedelta,
        *args,
        **kwargs
    ):
        """
        Just a dummy scheduler that always plans to consume at maximum capacity.
        (Schedulers return positive values for consumption, and negative values for production)
        """
        return initialize_series(  # simply creates a Pandas Series repeating one value
            data=sensor.get_attribute("capacity_in_mw"),
            start=start,
            end=end,
            resolution=resolution,
        )
