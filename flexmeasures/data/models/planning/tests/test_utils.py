import pandas as pd
from datetime import timedelta

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.utils import get_or_create_model
import timely_beliefs as tb
from flexmeasures.data.models.planning.utils import get_series_from_quantity_or_sensor


def test_get_series_from_quantity_or_sensor(
    db,
):
    asset_name = "battery"
    sensor_name = "power"
    query_window = (
        pd.Timestamp("2025-01-01 06:00:00+01:00"),
        pd.Timestamp("2025-01-01 06:15:00+01:00"),
    )
    source = get_or_create_model(DataSource, name="test-source")
    battery_type = get_or_create_model(GenericAssetType, name=asset_name)
    battery = get_or_create_model(
        GenericAsset, name=asset_name, generic_asset_type=battery_type
    )
    power_sensor = get_or_create_model(
        Sensor,
        name=sensor_name,
        generic_asset=battery,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )

    data = pd.DataFrame(
        {
            "event_start": pd.date_range(
                start=query_window[0], freq="15min", periods=1
            ),
            "event_value": [11],
        }
    )
    bdf = tb.BeliefsDataFrame(
        data,
        belief_horizon=pd.Timedelta(0),
        sensor=power_sensor,
        source=source,
        event_resolution=power_sensor.event_resolution,
    )
    TimedBelief.add(bdf)

    result = get_series_from_quantity_or_sensor(
        variable_quantity=power_sensor,
        query_window=query_window,
        resolution=power_sensor.event_resolution,
        unit="kW",
    )
    assert isinstance(result, pd.Series)
