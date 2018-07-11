from datetime import datetime, timedelta

from flask import current_app as app

from bvp.data.models.assets import Asset
from bvp.data.models.forecasting.solar import latest as solar_latest
from bvp.utils.time_utils import as_bvp_time


@app.cli.command()
def solar_model1():
    """Test integration of the ts-forecasting-pipeline"""

    start1 = as_bvp_time(datetime(2015, 2, 8))
    with app.app_context():
        asset = Asset.query.filter_by(asset_type_name="solar").first()
        solar_latest(
            asset,
            start=start1,
            end=start1 + timedelta(days=31),
            train_test_period=timedelta(days=30),
            evaluate=True,
        )
