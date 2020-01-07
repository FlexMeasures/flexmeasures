import pytest
from datetime import datetime, timedelta

from bvp.data.models.forecasting.utils import set_training_and_testing_window


@pytest.mark.parametrize(
    "forecast_horizon, training_and_testing_period",
    [
        (timedelta(minutes=-25), timedelta(days=1, minutes=30)),
        (timedelta(minutes=-15), timedelta(days=1, minutes=30)),
        (timedelta(minutes=-10), timedelta(days=1, minutes=15)),
        (timedelta(minutes=0), timedelta(days=1, minutes=15)),
        (timedelta(minutes=10), timedelta(days=1)),
        (timedelta(minutes=15), timedelta(days=1)),
        (timedelta(days=1), timedelta(minutes=15)),
        (timedelta(days=1, minutes=10), timedelta(minutes=0)),
        (timedelta(days=1, minutes=15), timedelta(minutes=0)),
    ],
)
def test_training_and_testing_window(forecast_horizon, training_and_testing_period):
    forecast_start = datetime(2000, 5, 2, 5, 15)
    resolution = timedelta(minutes=15)
    training_and_testing_window = set_training_and_testing_window(
        forecast_start, forecast_horizon, resolution, training_and_testing_period
    )
    assert (
        training_and_testing_window[1] - training_and_testing_window[0]
        == training_and_testing_period
    )
    assert training_and_testing_window[0] == datetime(2000, 5, 1, 5)
