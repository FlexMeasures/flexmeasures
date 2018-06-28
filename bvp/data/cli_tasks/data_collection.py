"""CLI tasks tasks to collect third-party data."""

import os

from flask import current_app as app
import click
import pytz
import pandas as pd


@app.cli.command()
def initialise_ts_pickles():
    """Import and clean data from CSV/Excel sheets into pickles"""
    from bvp.data.scripts.init_timeseries_data import initialise_all

    with app.app_context():
        initialise_all()


@app.cli.command()
def localize_ts_pickles():
    """Set the tz of all datetime indexes to Asia/Seoul"""
    for pickle in [p for p in os.listdir("raw_data/pickles") if p.endswith(".pickle")]:
        print(
            "Localising index of %s to %s ..."
            % (pickle, app.config.get("BVP_TIMEZONE"))
        )
        df = pd.read_pickle("raw_data/pickles/%s" % pickle)
        df.index = df.index.tz_localize(
            tz=pytz.timezone(app.config.get("BVP_TIMEZONE"))
        )
        df.to_pickle("raw_data/pickles/%s" % pickle)


@app.cli.command()
@click.option(
    "--region",
    type=str,
    default="",
    help="Name of the region (will create subfolder, should later tag the forecast in the DB, probably).",
)
@click.option("--num_cells", default=1, help="Number of cells on the grid.")
@click.option(
    "--method",
    default="hex",
    type=click.Choice(["hex", "square"]),
    help="Grid creation method.",
)
@click.option(
    "--top", type=float, required=True, help="Top latitude for region of interest."
)
@click.option(
    "--left", type=float, required=True, help="Left longitude for region of interest."
)
@click.option(
    "--bottom",
    type=float,
    required=True,
    help="Bottom latitude for region of interest.",
)
@click.option(
    "--right", type=float, required=True, help="Right longitude for region of interest."
)
def collect_weather_data(num_cells, region, method, top, left, bottom, right):
    """Collect weather data"""
    from bvp.data.scripts.grid_weather import get_weather_forecasts

    get_weather_forecasts(app, region, num_cells, method, top, left, bottom, right)
