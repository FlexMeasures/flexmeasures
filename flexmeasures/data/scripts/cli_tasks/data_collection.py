"""CLI tasks tasks to collect third-party data."""

from flask import current_app as app
import click


@app.cli.command()
@click.option(
    "--region",
    type=str,
    default="",
    help="Name of the region (will create sub-folder, should later tag the forecast in the DB, probably).",
)
@click.option(
    "--location",
    type=str,
    required=True,
    help='Measurement location(s). "latitude,longitude" or "top-left-latitude,top-left-longitude:'
    'bottom-right-latitude,bottom-right-longitude." The first format defines one location to measure.'
    " The second format defines a region of interest with several (>=4) locations"
    ' (see also the "method" and "num_cells" parameters for this feature).',
)
@click.option(
    "--num_cells",
    type=int,
    default=1,
    help="Number of cells on the grid. Only used if a region of interest has been mapped in the location parameter.",
)
@click.option(
    "--method",
    default="hex",
    type=click.Choice(["hex", "square"]),
    help="Grid creation method. Only used if a region of interest has been mapped in the location parameter.",
)
@click.option(
    "--store-in-db/--store-as-json-files",
    default=False,
    help="Store forecasts in the database, or simply save as json files.",
)
def collect_weather_data(region, location, num_cells, method, store_in_db):
    """Collect weather data for a grid. Leave bottom right empty for only one location (top left)."""
    from flexmeasures.data.scripts.grid_weather import get_weather_forecasts

    get_weather_forecasts(app, region, location, num_cells, method, store_in_db)
