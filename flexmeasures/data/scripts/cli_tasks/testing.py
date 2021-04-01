# flake8: noqa: E402
from typing import Optional
from datetime import datetime, timedelta
import os

from flask import current_app as app
import click
from timetomodel import ModelState, create_fitted_model, evaluate_models

if os.name == "nt":
    from rq_win import WindowsWorker as Worker
else:
    from rq import Worker

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensor
from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.utils.time_utils import as_server_time
from flexmeasures.data.services.forecasting import (
    create_forecasting_jobs,
    handle_forecasting_exception,
)

"""
These functions are meant for FlexMeasures developers to manually test some internal 
functionality.
They are not registered as app command per default, as we don't need to show them to users. 
"""

# un-comment to use as CLI function
# @app.cli.command()
def test_making_forecasts():
    """
    Manual test to enqueue and process a forecasting job via redis queue
    """

    click.echo("Manual forecasting job queuing started ...")

    asset_id = 1
    forecast_filter = (
        Power.query.filter(Power.asset_id == asset_id)
        .filter(Power.horizon == timedelta(hours=6))
        .filter(
            (Power.datetime >= as_server_time(datetime(2015, 4, 1, 6)))
            & (Power.datetime < as_server_time(datetime(2015, 4, 3, 6)))
        )
    )

    click.echo("Delete forecasts ...")
    forecast_filter.delete()
    click.echo("Forecasts found before : %d" % forecast_filter.count())

    create_forecasting_jobs(
        asset_id=asset_id,
        timed_value_type="Power",
        horizons=[timedelta(hours=6)],
        start_of_roll=as_server_time(datetime(2015, 4, 1)),
        end_of_roll=as_server_time(datetime(2015, 4, 3)),
    )

    click.echo("Queue before working: %s" % app.queues["forecasting"].jobs)

    worker = Worker(
        [app.queues["forecasting"]],
        connection=app.queues["forecasting"].connection,
        name="Test CLI Forecaster",
        exception_handlers=[handle_forecasting_exception],
    )
    worker.work()
    click.echo("Queue after working: %s" % app.queues["forecasting"].jobs)

    click.echo(
        "Forecasts found after (should be 24 * 2 * 4 = 192): %d"
        % forecast_filter.count()
    )


# un-comment to use as CLI function
# @app.cli.command()
@click.option("--asset-type", help="Asset type name.")
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
def test_generic_model(
    asset_type: str,
    asset: Optional[str] = None,
    from_date: str = "2015-03-10",
    period: int = 3,
    horizon: int = 1,
    training: int = 30,
):
    """Manually test integration of timetomodel for our generic model."""

    asset_type_name = asset_type
    if asset is None:
        asset_name = Asset.query.filter_by(asset_type_name=asset_type_name).first().name
    else:
        asset_name = asset
    start = as_server_time(datetime.strptime(from_date, "%Y-%m-%d"))
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

        linear_model_configurator = lookup_model_specs_configurator("linear")
        (
            model_specs,
            model_identifier,
            fallback_model_identifier,
        ) = linear_model_configurator(
            generic_asset=generic_asset,
            forecast_start=start,
            forecast_end=end,
            forecast_horizon=horizon,
            custom_model_params=dict(
                training_and_testing_period=training_and_testing_period
            ),
        )

        # Create and train the model
        model = create_fitted_model(model_specs, model_identifier)
        print("\n\nparams:\n%s\n\n" % model.params)

        evaluate_models(m1=ModelState(model, model_specs), plot_path=None)

        return ModelState(model, model_specs)
