#!/usr/bin/env python

import os
from typing import Tuple, List
import json
from datetime import datetime

import click
from flask import Flask, current_app
from forecastiopy import ForecastIO

from flexmeasures.utils.time_utils import as_server_time, get_timezone
from flexmeasures.utils.geo_utils import compute_irradiance
from flexmeasures.data.services.resources import find_closest_weather_sensor
from flexmeasures.data.config import db
from flexmeasures.data.transactional import task_with_status_report
from flexmeasures.data.models.weather import Weather
from flexmeasures.data.models.data_sources import DataSource

FILE_PATH_LOCATION = "/../raw_data/weather-forecasts"
DATA_SOURCE_NAME = "DarkSky"


class LatLngGrid(object):
    """
    Represents a grid in latitude and longitude notation for some rectangular region of interest (ROI).
    The specs are a top-left and a bottom-right coordinate, as well as the number of cells in both directions.
    The class provides two ways of conceptualising cells which nicely cover the grid: square cells and hexagonal cells.
    For both, locations can be computed which represent the corners of said cells.
    Examples:
          - 4 cells in square: 9 unique locations in a 2x2 grid (4*4 locations, of which 7 are covered by another cell)
          - 4 cells in hex: 13 unique locations in a 2x2 grid (4*6 locations, of which 11 are already covered)
          - 10 cells in square: 18 unique locations in a 5x2 grid (10*4 locations, of which 11 are already covered)
          - 10 cells in hex: 34 unique locations in a 5x2 grid (10*6 locations, of which 26 are already covered)
    The top-right and bottom-left locations are always at the center of a cell, unless the grid has 1 row or 1 column.
    In those case, these locations are closer to one side of the cell.
    """

    top_left: Tuple[float, float]
    bottom_right: Tuple[float, float]
    num_cells_lat: int
    num_cells_lng: int

    def __init__(
        self,
        top_left: Tuple[float, float],
        bottom_right: Tuple[float, float],
        num_cells_lat: int,
        num_cells_lng: int,
    ):
        self.top_left = top_left
        self.bottom_right = bottom_right
        self.num_cells_lat = num_cells_lat
        self.num_cells_lng = num_cells_lng
        self.cell_size_lat = self.compute_cell_size_lat()
        self.cell_size_lng = self.compute_cell_size_lng()

        # correct top-left and bottom-right if there is only one cell
        if self.num_cells_lat == 1:  # if only one row
            self.top_left = (
                self.top_left[0] + self.cell_size_lat / 4,
                self.top_left[1],
            )
            self.bottom_right = (
                self.bottom_right[0] - self.cell_size_lat / 4,
                self.bottom_right[1],
            )
        if self.num_cells_lng == 1:
            self.top_left = (
                self.top_left[0],
                self.top_left[1] + self.cell_size_lng / 4,
            )
            self.bottom_right = (
                self.bottom_right[0],
                self.bottom_right[1] - self.cell_size_lng / 4,
            )

    def __repr__(self) -> str:
        return (
            f"<LatLngGrid top-left:{self.top_left}, bot-right:{self.bottom_right},"
            + f"num_lat:{self.num_cells_lat}, num_lng:{self.num_cells_lng}>"
        )

    def get_locations(self, method: str) -> List[Tuple[float, float]]:
        """Get locations by method ("square" or "hex")"""
        click.echo(self)
        click.echo()

        if method == "hex":
            locations = self.locations_hex()
            click.echo(
                "[FLEXMEASURES] Number of locations in hex grid: "
                + str(len(self.locations_hex()))
            )
            return locations
        elif method == "square":
            locations = self.locations_square()
            click.echo(
                "[FLEXMEASURES] Number of locations in square grid: "
                + str(len(self.locations_square()))
            )
            return locations
        else:
            raise Exception(
                "Method must either be 'square' or 'hex'! (is: %s)" % method
            )

    def compute_cell_size_lat(self) -> float:
        """Calculate the step size between latitudes"""
        if self.num_cells_lat != 1:
            return (self.bottom_right[0] - self.top_left[0]) / (self.num_cells_lat - 1)
        else:
            return (self.bottom_right[0] - self.top_left[0]) * 2

    def compute_cell_size_lng(self) -> float:
        """Calculate the step size between longitudes"""
        if self.num_cells_lng != 1:
            return (self.bottom_right[1] - self.top_left[1]) / (self.num_cells_lng - 1)
        else:
            return (self.bottom_right[1] - self.top_left[1]) * 2

    def locations_square(self) -> List[Tuple[float, float]]:
        """square pattern"""
        locations = []

        # For each odd cell row, add all the coordinates of the row's cells
        for ilat in range(0, self.num_cells_lat, 2):
            lat = self.top_left[0] + ilat * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                nw = (
                    lat - self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # North west coordinate of the cell
                locations.append(nw)
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # South west coordinate
                locations.append(sw)
            ne = (
                lat - self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # North east coordinate
            locations.append(ne)
            se = (
                lat + self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # South east coordinate
            locations.append(se)

        # In case of an even number of cell rows, add the southern coordinates of the southern most row
        if not self.num_cells_lat % 2:
            lat = self.top_left[0] + (self.num_cells_lat - 1) * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lng / 2,
                )  # South west coordinate
                locations.append(sw)
            se = (
                lat + self.cell_size_lat / 2,
                lng + self.cell_size_lng / 2,
            )  # South east coordinate
            locations.append(se)

        return locations

    def locations_hex(self) -> List[Tuple[float, float]]:
        """The hexagonal pattern - actually leaves out one cell for every even row."""
        locations = []

        # For each odd cell row, add all the coordinates of the row's cells
        for ilat in range(0, self.num_cells_lat, 2):
            lat = self.top_left[0] + ilat * self.cell_size_lat
            for ilng in range(self.num_cells_lng):
                lng = self.top_left[1] + ilng * self.cell_size_lng
                n = (
                    lat - self.cell_size_lat * 2 / 3,
                    lng,
                )  # North coordinate of the cell
                locations.append(n)
                nw = (
                    lat - self.cell_size_lat * 1 / 4,
                    lng - self.cell_size_lng * 1 / 2,
                )  # North west coordinate
                locations.append(nw)
                s = (lat + self.cell_size_lat * 2 / 3, lng)  # South coordinate
                locations.append(s)
                sw = (
                    lat + self.cell_size_lat * 1 / 4,
                    lng - self.cell_size_lng * 1 / 2,
                )  # South west coordinate
                locations.append(sw)
            ne = (
                lat - self.cell_size_lat * 1 / 4,
                lng + self.cell_size_lng * 1 / 2,
            )  # North east coordinate
            locations.append(ne)
            se = (
                lat + self.cell_size_lat * 1 / 4,
                lng + self.cell_size_lng * 1 / 2,
            )  # South east coordinate
            locations.append(se)

        # In case of an even number of cell rows, add the southern coordinates of the southern most row
        if not self.num_cells_lat % 2:
            lat = self.top_left[0] + (self.num_cells_lat - 1) * self.cell_size_lat
            for ilng in range(
                self.num_cells_lng - 1
            ):  # One less cell in even rows of hexagonal locations
                # Cells are shifted half a cell to the right in even rows of hex locations
                lng = self.top_left[1] + (ilng + 1 / 2) * self.cell_size_lng
                s = (lat + self.cell_size_lat / 3 ** (1 / 2), lng)  # South coordinate
                locations.append(s)
                sw = (
                    lat + self.cell_size_lat / 2,
                    lng - self.cell_size_lat / 3 ** (1 / 2) / 2,
                )  # South west coord.
                locations.append(sw)
                se = (
                    lat + self.cell_size_lat / 2,
                    lng + self.cell_size_lng / 3 ** (1 / 2) / 2,
                )  # South east coord.
                locations.append(se)
        return locations


def get_cell_nums(
    tl: Tuple[float, float], br: Tuple[float, float], num_cells: int = 9
) -> Tuple[int, int]:
    """
    Compute the number of cells in both directions, latitude and longitude.
    By default, a square grid with N=9 cells is computed, so 3 by 3.
    For N with non-integer square root, the function will determine a nice cell pattern.
    :param tl: top-left (lat, lng) tuple of ROI
    :param br: bottom-right (lat, lng) tuple of ROI
    :param num_cells: number of cells (9 by default, leading to a 3x3 grid)
    """

    def factors(n):
        """Factors of a number n"""
        return set(
            factor
            for i in range(1, int(n ** 0.5) + 1)
            if n % i == 0
            for factor in (i, n // i)
        )

    # Find closest integers n1 and n2 that, when multiplied, equal n
    n1 = min(factors(num_cells), key=lambda x: abs(x - num_cells ** (1 / 2)))
    n2 = num_cells // n1

    # Assign largest integer to lat or lng depending on which has the largest spread (earth curvature neglected)
    if br[0] - tl[0] > br[1] - tl[1]:
        return max(n1, n2), min(n1, n2)
    else:
        return min(n1, n2), max(n1, n2)


def get_region_from_assets() -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Create a suitable region of interest from all asset locations.
    Currently not used. (we simply pass top left and bottom right to this script).
    Should in any case later probably contact the database actually.
    """
    assets_path = "../raw_data/assets.json"
    lats, lngs = [], []
    if os.path.exists(assets_path):
        with open(assets_path, "r") as json_data:
            assets = json.load(json_data)
    else:
        raise Exception("File not found: %s" % assets_path)

    for asset in assets:
        if "latitude" in asset and "longitude" in asset:
            lats.append(asset["latitude"])
            lngs.append(asset["longitude"])
        else:
            click.echo(
                "[FLEXMEASURES] Asset %s has no latitude and/or longitude."
                % asset["name"]
            )
    top_left = min(lats), min(lngs)
    bottom_right = max(lats), max(lngs)
    return top_left, bottom_right


def make_file_path(app: Flask, region: str) -> str:
    """Ensure and return path for weather data"""
    data_path = app.root_path + FILE_PATH_LOCATION
    if not os.path.exists(data_path):
        if os.path.exists(app.root_path + "/../raw_data"):
            click.echo("[FLEXMEASURES] Creating %s ..." % data_path)
            os.mkdir(data_path)
        else:
            raise Exception("No %s/../raw_data directory found." % app.root_path)
    # optional: extend with subpath for region
    if region is not None and region != "":
        region_data_path = "%s/%s" % (data_path, region)
        if not os.path.exists(region_data_path):
            click.echo("[FLEXMEASURES] Creating %s ..." % region_data_path)
            os.mkdir(region_data_path)
        data_path = region_data_path
    return data_path


def get_data_source() -> DataSource:
    """Make sure we have a data source"""
    data_source = DataSource.query.filter_by(
        name=DATA_SOURCE_NAME, type="forecasting script"
    ).one_or_none()
    if data_source is None:
        data_source = DataSource(name=DATA_SOURCE_NAME, type="forecasting script")
        db.session.add(data_source)
    return data_source


def call_darksky(api_key: str, location: Tuple[float, float]) -> dict:
    """Make a single call to the Dark Sky API and return the result parsed as dict"""
    return ForecastIO.ForecastIO(
        api_key,
        units=ForecastIO.ForecastIO.UNITS_SI,
        lang=ForecastIO.ForecastIO.LANG_ENGLISH,
        latitude=location[0],
        longitude=location[1],
        extend="hourly",
    ).forecast


def save_forecasts_in_db(
    api_key: str, locations: List[Tuple[float, float]], data_source: DataSource
):
    """Process the response from DarkSky into Weather timed values.
    Collects all forecasts for all locations and all sensors at all locations, then bulk-saves them.
    """
    click.echo("[FLEXMEASURES] Getting weather forecasts:")
    click.echo("[FLEXMEASURES]  Latitude, Longitude")
    click.echo("[FLEXMEASURES] -----------------------")
    db_forecasts = []
    weather_sensors: dict = {}  # keep track of the sensors to save lookups

    for location in locations:
        click.echo("[FLEXMEASURES] %s, %s" % location)

        forecasts = call_darksky(api_key, location)
        time_of_api_call = as_server_time(
            datetime.fromtimestamp(forecasts["currently"]["time"], get_timezone())
        ).replace(second=0, microsecond=0)
        click.echo(
            "[FLEXMEASURES] Called Dark Sky API successfully at %s." % time_of_api_call
        )

        # map sensor name in our db to sensor name/label in dark sky response
        sensor_name_mapping = dict(
            temperature="temperature", wind_speed="windSpeed", radiation="cloudCover"
        )

        for fc in forecasts["hourly"]["data"]:
            fc_datetime = as_server_time(
                datetime.fromtimestamp(fc["time"], get_timezone())
            ).replace(second=0, microsecond=0)
            fc_horizon = fc_datetime - time_of_api_call
            click.echo(
                "[FLEXMEASURES] Processing forecast for %s (horizon: %s) ..."
                % (fc_datetime, fc_horizon)
            )
            for flexmeasures_sensor_type in sensor_name_mapping.keys():
                needed_response_label = sensor_name_mapping[flexmeasures_sensor_type]
                if needed_response_label in fc:
                    weather_sensor = weather_sensors.get(flexmeasures_sensor_type, None)
                    if weather_sensor is None:
                        weather_sensor = find_closest_weather_sensor(
                            flexmeasures_sensor_type, lat=location[0], lng=location[1]
                        )
                        if weather_sensor is not None:
                            weather_sensors[flexmeasures_sensor_type] = weather_sensor
                        else:
                            raise Exception(
                                "No weather sensor set up for this sensor type (%s)"
                                % flexmeasures_sensor_type
                            )

                    fc_value = fc[needed_response_label]
                    # the radiation is not available in dark sky -> we compute it ourselves
                    if flexmeasures_sensor_type == "radiation":
                        fc_value = compute_irradiance(
                            location[0],
                            location[1],
                            fc_datetime,
                            fc[needed_response_label],
                        )

                    db_forecasts.append(
                        Weather(
                            datetime=fc_datetime,
                            horizon=fc_horizon,
                            value=fc_value,
                            sensor_id=weather_sensor.id,
                            data_source_id=data_source.id,
                        )
                    )
                else:
                    # we will not fail here, but issue a warning
                    msg = "No label '%s' in response data for time %s" % (
                        needed_response_label,
                        fc_datetime,
                    )
                    click.echo("[FLEXMEASURES] %s" % msg)
                    current_app.logger.warning(msg)
    if len(db_forecasts) == 0:
        # This is probably a serious problem
        raise Exception(
            "Nothing to put in the database was produced. That does not seem right..."
        )
    db.session.bulk_save_objects(db_forecasts)


def save_forecasts_as_json(
    api_key: str, locations: List[Tuple[float, float]], data_path: str
):
    """Get forecasts, then store each as a JSON file"""
    click.echo("[FLEXMEASURES] Getting weather forecasts:")
    click.echo("[FLEXMEASURES]  Latitude, Longitude")
    click.echo("[FLEXMEASURES]  ----------------------")
    # UTC timestamp to remember when data was fetched.
    now_str = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    os.mkdir("%s/%s" % (data_path, now_str))
    for location in locations:
        click.echo("[FLEXMEASURES] %s, %s" % location)
        forecasts = call_darksky(api_key, location)
        forecasts_file = "%s/%s/forecast_lat_%s_lng_%s.json" % (
            data_path,
            now_str,
            str(location[0]),
            str(location[1]),
        )
        with open(forecasts_file, "w") as outfile:
            json.dump(forecasts, outfile)


@task_with_status_report
def get_weather_forecasts(
    app: Flask,
    region: str,
    location: str,
    num_cells: int,
    method: str,
    store_in_db: bool,
):
    """
    Get current weather forecasts for a latitude/longitude grid and store them in individual json files.
    Note that 1000 free calls per day can be made to the Dark Sky API,
    so we can make a call every 15 minutes for up to 10 assets or every hour for up to 40 assets.
    """
    if app.config.get("DARK_SKY_API_KEY") is None:
        raise Exception("No DarkSky API key available.")

    if (
        location.count(",") == 0
        or location.count(",") != location.count(":") + 1
        or location.count(":") == 1
        and (
            location.find(",") > location.find(":")
            or location.find(",", location.find(",") + 1) < location.find(":")
        )
    ):
        raise Exception(
            'location parameter "%s" seems malformed. Please use "latitude,longitude" or '
            ' "top-left-latitude,top-left-longitude:bottom-right-latitude,bottom-right-longitude"'
            % location
        )

    location_identifiers = tuple(location.split(":"))

    if len(location_identifiers) == 1:
        locations = [tuple(float(s) for s in location_identifiers[0].split(","))]
        click.echo("[FLEXMEASURES] Only one location: %s,%s." % locations[0])
    elif len(location_identifiers) == 2:
        click.echo(
            "[FLEXMEASURES] Making a grid of locations between top/left %s and bottom/right %s ..."
            % location_identifiers
        )
        top_left = tuple(float(s) for s in location_identifiers[0].split(","))
        if len(top_left) != 2:
            raise Exception(
                "top-left parameter '%s' is invalid." % location_identifiers[0]
            )
        bottom_right = tuple(float(s) for s in location_identifiers[1].split(","))
        if len(bottom_right) != 2:
            raise Exception(
                "bottom-right parameter '%s' is invalid." % location_identifiers[1]
            )

        num_lat, num_lng = get_cell_nums(top_left, bottom_right, num_cells)

        locations = LatLngGrid(
            top_left=top_left,
            bottom_right=bottom_right,
            num_cells_lat=num_lat,
            num_cells_lng=num_lng,
        ).get_locations(method)
    else:
        raise Exception("location parameter '%s' has too many locations." % location)

    api_key = app.config.get("DARK_SKY_API_KEY")

    # Save the results
    if store_in_db:
        save_forecasts_in_db(api_key, locations, data_source=get_data_source())
    else:
        save_forecasts_as_json(
            api_key, locations, data_path=make_file_path(app, region)
        )
