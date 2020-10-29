from datetime import timedelta
import pickle

from flask import Flask, render_template
import pandas as pd

from empras.utils import determine_time_window_from_request, slice_data

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


WIDTH = 600
HEIGHT = 300


@app.route(
    "/chart/<chart_type>/<dataset_name>"
)  # todo: probably this route should get a more standard logic
def get_chart(chart_type: str, dataset_name: str):
    """

    :param chart_type: used to select between available visualisations
    :param dataset_name: used to assign a name to the dataset
    """
    time_format = "%I %p on %A %b %e, %Y"
    return {
        # "$schema": "https://vega.github.io/schema/vega-lite/v3.json",
        "description": "A simple bar chart missing a data url.",
        "width": WIDTH,
        "height": HEIGHT,
        "data": {
            "name": dataset_name,
        },
        "mark": "bar",
        "transform": [
            {"as": "full_date", "calculate": f"timeFormat(datum.dt, '{time_format}')"}
        ],
        "encoding": {
            "x": {"field": "dt", "type": "T"},
            "y": {"field": "k", "type": "quantitative"},
            "tooltip": [
                {"field": "full_date", "title": "Time and date", "type": "nominal"},
                {"field": "k", "title": "Consumption rate", "type": "quantitative"},
            ],
        },
    }


@app.route("/sensor/<int:sensor_id>", methods=["GET"])
def get_sensor(sensor_id: int):

    # todo: get the time range from the sensor
    start = pd.Timestamp("2018-1-1")
    end = pd.Timestamp("2020-1-2")

    # todo: get the timezone from the sensor
    tz = "America/Los_Angeles"

    return {"time_range": {"start": start, "end": end}, "timezone": tz}


@app.route("/sensor/<int:sensor_id>/processes", methods=["GET"])
def get_processes(sensor_id: int):

    # Load data
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    with open("empras/data/analysis.pickle", "rb") as f:
        (
            df,
            group_sizes,
            resolution,
            duration_unit_str,
            duration_unit,
            k_range,
            d_range,
            tz,
        ) = pickle.load(f)
    df["dt"] = pd.to_datetime(df["dt"], unit="ms").dt.tz_localize(tz)
    df = df.set_index("dt")

    # Interpret requested time window and slice
    start, end = determine_time_window_from_request(df, tz)
    df = slice_data(df, start, end, resolution)

    return df.reset_index().to_json(orient="records")


@app.route("/sensor/<int:sensor_id>/data", methods=["GET"])
def get_data(sensor_id: int):
    """

    About timezones
    ---------------
    By default, the requested date range is interpreted in the timezone of the sensor.
    The caller can override this by setting a timezone explicitly. Note that in both cases,
    the UI probably shows times in the caller's local timezone (as derived from their locale setting).
    """

    # Load data
    resolution = timedelta(
        hours=1
    )  # todo 1: get resolution from sensor, todo 2: query sensor from request
    tz = "America/Los_Angeles"  # todo: get tz from sensor
    dates = pd.date_range(
        "2000", "2010", freq=resolution, name="dt", tz=tz, closed="left"
    )  # todo: get from request
    df = pd.DataFrame(
        range(len(dates)), index=dates, columns=["k"]
    )  # todo 1: get from beliefs, todo 2: get beliefs from sensor

    # Interpret requested time window and slice
    start, end = determine_time_window_from_request(df, tz)
    df = slice_data(df, start, end, resolution)

    # Return data
    return df.reset_index().to_json(orient="records")


if __name__ == "__main__":
    app.run(debug=True)
