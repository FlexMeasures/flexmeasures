# flake8: noqa: E402
from __future__ import annotations

from datetime import datetime, timedelta
import os

from flask import current_app as app
import click

if os.name == "nt":
    from rq_win import WindowsWorker as Worker
else:
    from rq import Worker

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.utils.time_utils import as_server_time
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.services.forecasting import handle_forecasting_exception

"""
These functions are meant for FlexMeasures developers to manually test some internal 
functionality.
They are not registered as app command per default, as we don't need to show them to users. 
"""


# un-comment to use as CLI function
# @app.cli.command()
def test_making_forecasts():
    """
    Manual test to enqueue and process a fixed-viewpoint forecasting job via redis queue.
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

    pipeline = TrainPredictPipeline(
        config={
            "train-start": "2015-03-01T00:00:00+00:00",
            "retrain-frequency": "PT24H",
        }
    )
    pipeline.compute(
        as_job=True,
        parameters={
            "sensor": sensor_id,
            "start": as_server_time(datetime(2015, 4, 1)).isoformat(),
            "end": as_server_time(datetime(2015, 4, 3)).isoformat(),
            "max-forecast-horizon": "PT6H",
            "forecast-frequency": "PT24H",
        },
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
        "Forecasts found after processing the queue: %d" % forecast_filter.count()
    )
