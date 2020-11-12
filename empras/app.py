from datetime import timedelta
import pickle

from flask import abort, Flask, render_template
import pandas as pd

from empras.charts import belief_charts_mapping, process_charts_mapping
from empras.utils import (
    add_none_rows_to_help_charts,
    determine_time_window_from_request,
    slice_data,
)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route(
    "/chart/<data_structure>/<chart_type>/<dataset_name>/<agg_demand_unit>"
)  # todo: probably this route should get a more standard logic
# todo: move dataset_name and agg_demand_unit to url parameters or json load
def get_chart(
    data_structure: str, chart_type: str, dataset_name: str, agg_demand_unit: str
):
    """

    :param data_structure: "processes" or "data"
    :param chart_type: used to select between available visualisations
    :param dataset_name: used to assign a name to the dataset
    :param agg_demand_unit: unit for total consumption, such as m3 or kWh (a stock, not a flow)
    """
    kwargs = dict(
        dataset_name=dataset_name,
        agg_demand_unit=agg_demand_unit,
    )

    if data_structure == "processes":
        return process_charts_mapping[chart_type](**kwargs)
    elif data_structure == "data":
        return belief_charts_mapping[chart_type](**kwargs)
    elif data_structure in ["sensors", "assets"]:
        # todo: return a map plotting their location
        abort(404)
    else:
        abort(404)


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
    df = df.set_index("dt").dropna()

    # Interpret requested time window and slice
    start, end = determine_time_window_from_request(df, tz)
    df = slice_data(df, start, end)
    df = add_none_rows_to_help_charts(df, start, end, resolution)
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
    df = slice_data(df, start, end)
    df = add_none_rows_to_help_charts(df, start, end, resolution)

    # Return data
    return df.reset_index().to_json(orient="records")


if __name__ == "__main__":
    app.run(debug=True)
