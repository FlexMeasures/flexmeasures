from datetime import datetime, timedelta

import pandas as pd

from flexmeasures.data.models.time_series import Sensor


def compute_a_schedule(
    sensor: Sensor,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    *args,
    **kwargs
):
    """Just a dummy scheduler."""
    return pd.Series(
        sensor.get_attribute("capacity_in_mw"),
        index=pd.date_range(start, end, freq=resolution, inclusive="left"),
    )
