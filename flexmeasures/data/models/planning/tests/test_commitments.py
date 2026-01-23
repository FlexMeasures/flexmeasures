import pandas as pd

from flexmeasures.data.models.planning import StockCommitment
from flexmeasures.data.models.planning.utils import initialize_index


def test_multi_feed():
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-02T00:00+01")
    resolution = pd.Timedelta("PT1H")
    index = (initialize_index(start=start, end=end, resolution=resolution),)

    device_group = pd.Series(
        {
            "gas boiler": "shared thermal buffer",
            "heat pump power": "shared thermal buffer",
            "battery power": "battery SoC",
        }
    )

    max_thermal_soc = "100 kWh"
    breach_price = "1000 EUR/kWh"

    commitment_a = StockCommitment(
        name="buffer max",
        index=index,
        quantity=max_thermal_soc,
        upwards_deviation_price=breach_price,
        downwards_deviation_price=0,
        device=pd.Series(
            "gas boiler", index=index
        ),  # per-slot device resolution happens elsewhere
        device_group=device_group,
    )
    commitment_b = StockCommitment(
        name="buffer max",
        index=index,
        quantity=max_thermal_soc,
        upwards_deviation_price=breach_price,
        downwards_deviation_price=0,
        device=pd.Series(
            "heat pump power", index=index
        ),  # per-slot device resolution happens elsewhere
        device_group=device_group,
    )
    commitment_c = StockCommitment(
        name="buffer max",
        index=index,
        quantity=max_thermal_soc,
        upwards_deviation_price=breach_price,
        downwards_deviation_price=0,
        device=pd.Series(
            "battery power", index=index
        ),  # per-slot device resolution happens elsewhere
        device_group=device_group,
    )
    assert commitment_a.device_group[0] == "shared thermal buffer"
    assert commitment_b.device_group[0] == "shared thermal buffer"
    assert commitment_c.device_group[0] == "battery SoC"
