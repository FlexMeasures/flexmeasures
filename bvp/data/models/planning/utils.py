from typing import List, Optional, Union
from datetime import date, datetime, timedelta

import pandas as pd
from pandas.tseries.frequencies import to_offset
import numpy as np


def initialize_df(
    columns: List[str], start: datetime, end: datetime, resolution: timedelta
) -> pd.DataFrame:
    df = pd.DataFrame(index=initialize_index(start, end, resolution), columns=columns)
    return df


def initialize_series(
    data: Optional[Union[pd.Series, List[float], np.ndarray, float]],
    start: datetime,
    end: datetime,
    resolution: timedelta,
) -> pd.Series:
    s = pd.Series(index=initialize_index(start, end, resolution), data=data)
    return s


def initialize_index(
    start: Union[date, datetime], end: Union[date, datetime], resolution: timedelta
) -> pd.DatetimeIndex:
    i = pd.date_range(
        start=start, end=end, freq=to_offset(resolution), closed="left", name="datetime"
    )
    return i
