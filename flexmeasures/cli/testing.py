# flake8: noqa: E402
from __future__ import annotations

from datetime import datetime, timedelta
import os

from flask import current_app as app
import click
from timetomodel import ModelState, create_fitted_model, evaluate_models

if os.name == "nt":
    from rq_win import WindowsWorker as Worker
else:
    from rq import Worker

from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.queries.sensors import (
    query_sensor_by_name_and_generic_asset_type_name,
)
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

    sensor_id = 1
    forecast_filter = (
        TimedBelief.query.filter(TimedBelief.sensor_id == sensor_id)
        .filter(TimedBelief.belief_horizon == timedelta(hours=6))
        .filter(
            (TimedBelief.event_start >= as_server_time(datetime(2015, 4, 1, 6)))
            & (TimedBelief.event_start < as_server_time(datetime(2015, 4, 3, 6)))
        )
    )

    click.echo("Delete forecasts ...")
    forecast_filter.delete()
    click.echo("Forecasts found before : %d" % forecast_filter.count())

    create_forecasting_jobs(
        sensor_id=sensor_id,
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
@click.option(
    "--asset-type",
    "generic_asset_type_names",
    multiple=True,
    required=True,
    help="Name of generic asset type.",
)
@click.option("--sensor", "sensor_name", help="Name of sensor.")
@click.option(
    "--from_date",
    default="2015-03-10",
    help="Forecast from date. Follow up with a date in the form yyyy-mm-dd.",
)
@click.option("--period", default=3, help="Forecasting period in days.")
@click.option(
    "--horizon", "horizon_hours", default=1, help="Forecasting horizon in hours."
)
@click.option(
    "--training", default=30, help="Number of days in the training and testing period."
)
def test_generic_model(
    generic_asset_type_names: list[str],
    sensor_name: str | None = None,
    from_date: str = "2015-03-10",
    period: int = 3,
    horizon_hours: int = 1,
    training: int = 30,
):
    """Manually test integration of timetomodel for our generic model."""

    start = as_server_time(datetime.strptime(from_date, "%Y-%m-%d"))
    end = start + timedelta(days=period)
    training_and_testing_period = timedelta(days=training)
    horizon = timedelta(hours=horizon_hours)

    with app.app_context():
        sensors = query_sensor_by_name_and_generic_asset_type_name(
            sensor_name=sensor_name,
            generic_asset_type_names=generic_asset_type_names,
        ).all()
        if len(sensors) == 0:
            click.echo("No such sensor in db, so I will not add any forecasts.")
            raise click.Abort()
        elif len(sensors) > 1:
            click.echo("No unique sensor found in db, so I will not add any forecasts.")
            raise click.Abort()

        linear_model_configurator = lookup_model_specs_configurator("linear")
        (
            model_specs,
            model_identifier,
            fallback_model_identifier,
        ) = linear_model_configurator(
            sensor=sensors[0],
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
