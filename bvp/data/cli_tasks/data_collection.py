"""CLI tasks tasks to collect third-party data."""

from flask import current_app as app
import click


@app.cli.command()
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
def collect_weather_data(num_cells, method, top, left, bottom, right):
    """Collect weather data"""
    from bvp.data.scripts.grid_weather import get_weather_forecasts

    get_weather_forecasts(app, num_cells, method, top, left, bottom, right)
