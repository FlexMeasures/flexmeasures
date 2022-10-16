from datetime import datetime, timedelta

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.planning.utils import initialize_series


def compute_a_schedule(
    sensor: Sensor,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    *args,
    **kwargs
):
    """Just a dummy scheduler."""
    return initialize_series(  # simply creates a Pandas Series repeating one value
        data=sensor.get_attribute("capacity_in_mw"),
        start=start,
        end=end,
        resolution=resolution,
    )
