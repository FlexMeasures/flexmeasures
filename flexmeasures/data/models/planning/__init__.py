from typing import Optional
import pandas as pd


class Scheduler:
    """
    Superclass for all FlexMeasures Schedulers
    """

    def schedule(*args, **kwargs) -> Optional[pd.Series]:
        return None
