from typing import Optional
from datetime import datetime, timedelta

from flask import current_app as app
import click

from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensor
from bvp.data.models.forecasting.generic import latest_model as latest_generic_model
from bvp.utils.time_utils import as_bvp_time
from ts_forecasting_pipeline import ModelState, create_fitted_model, evaluate_models


@app.cli.command()
@click.option("--type", help="Asset type name.")
@click.option("--asset", help="Asset name.")
@click.option(
    "--from_date",
    default="2015-03-10",
    help="Forecast from date. Follow up with a date in the form yyyy-mm-dd.",
)
@click.option("--period", default=3, help="Forecasting period in days.")
@click.option("--horizon", default=1, help="Forecasting horizon in hours.")
@click.option(
    "--training", default=30, help="Number of days in the training and testing period."
)
def generic_model(
    type: str,
    asset: Optional[str] = None,
    from_date: str = "2015-03-10",
    period: int = 3,
    horizon: int = 1,
    training: int = 30,
):
    """Test integration of the ts-forecasting-pipeline for our generic model."""

    asset_type_name = type
    if asset is None:
        asset_name = Asset.query.filter_by(asset_type_name=asset_type_name).first().name
    else:
        asset_name = asset
    start = as_bvp_time(datetime.strptime(from_date, "%Y-%m-%d"))
    end = start + timedelta(days=period)
    training_and_testing_period = timedelta(days=training)
    horizon = timedelta(hours=horizon)

    with app.app_context():
        asset = (
            Asset.query.filter_by(asset_type_name=asset_type_name)
            .filter_by(name=asset_name)
            .first()
        )
        market = (
            Market.query.filter_by(market_type_name=asset_type_name)
            .filter_by(name=asset_name)
            .first()
        )
        sensor = (
            WeatherSensor.query.filter_by(weather_sensor_type_name=asset_type_name)
            .filter_by(name=asset_name)
            .first()
        )
        if asset:
            generic_asset = asset
        elif market:
            generic_asset = market
        elif sensor:
            generic_asset = sensor
        else:
            click.echo("No such assets in db, so I will not add any forecasts.")
            return

        model_specs, model_identifier = latest_generic_model(
            generic_asset=generic_asset,
            start=start,
            end=end,
            training_and_testing_period=training_and_testing_period,
            horizon=horizon,
        )

        # Create and train the model
        model = create_fitted_model(model_specs, model_identifier)
        print("\n\nparams:\n%s\n\n" % model.params)

        evaluate_models(m1=ModelState(model, model_specs), plot_path=None)

        return ModelState(model, model_specs)
