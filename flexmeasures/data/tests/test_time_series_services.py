import pandas as pd
from timely_beliefs import utils as tb_utils

from flexmeasures.api.common.utils.api_utils import save_to_db

from flexmeasures.data.models.time_series import Sensor


def test_drop_unchanged_beliefs(setup_beliefs):
    """Trying to save beliefs that are already in the database shouldn't raise an error.

    Even after updating the belief time, we expect to persist only the older belief time.
    """
    sensor = Sensor.query.filter_by(name="epex_da").one_or_none()
    bdf = sensor.search_beliefs()
    num_beliefs_before = len(bdf)
    belief_times_before = bdf.belief_times
    save_to_db(bdf)  # try saving verbatim
    bdf = sensor.search_beliefs()
    assert len(bdf) == num_beliefs_before
    bdf = tb_utils.replace_multi_index_level(
        bdf, "belief_time", bdf.belief_times + pd.Timedelta("1H")
    )
    save_to_db(bdf)  # try saving with updated belief time
    bdf = sensor.search_beliefs()
    assert len(bdf) == num_beliefs_before
    assert list(bdf.belief_times) == list(belief_times_before)
