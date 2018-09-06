#!/usr/bin/env python

"""
Script for loading and pickling dataframes from the Excel Spreadsheet we got from A1 with 2015 data.
When we move to a database, this will change.
Each pickle encodes in its name the asset name and resolution. Asset name should refer to a name in assets.json of
course, we might add a check or warning here.
"""
import os
import collections

import pytz
import pandas as pd

from bvp.data.models.assets import Asset, AssetType  # noqa: E402
from bvp.data.models.markets import Market, MarketType  # noqa: E402


path_to_input_data = "raw_data/time-series"  # assuming we are in the main directory
path_to_pickles = "raw_data/pickles"  # assuming we are in the main directory

# all these data sources are assumed to be in the data directory
asset_excel_filename = "20171120_A1-VPP_DesignDataSetR01.xls"
weather_excel_filename = "20171120_A1-VPP_DesignDataSetR01.xls"
prices_filename = "German day-ahead prices 20140101-20160630.csv"
evs_filename = "German charging stations 20150101-20150620.csv"
buildings_filename = "neighbourhood.csv"


def set_datetime_index(
    old_df: pd.DataFrame, freq: str, start=None, timezone=pytz.UTC
) -> pd.DataFrame:
    """Construct a new datetime index from the starting date and length of the data, and apply it"""
    if start is None:
        ix = pd.DatetimeIndex(
            start=old_df.index[0], periods=len(old_df.index), freq=freq
        )
    else:
        ix = pd.DatetimeIndex(start=start, periods=len(old_df.index), freq=freq)
    return pd.DataFrame(
        data=old_df.to_dict(orient="records"), index=ix.tz_localize(tz=timezone)
    )


def timeseries_resample(the_df: pd.DataFrame, the_res: str) -> pd.DataFrame:
    """Sample time series for given resolution, using the mean for downsampling and a forward fill for upsampling"""

    # Both of these preferred methods (choose one) are not correctly supported yet in pandas 0:22:0
    # res_df = df.resample(res, how='mean', fill_method='pad')
    # res_df = df.resample(res).mean().pad()

    tmp_df = pd.date_range(the_df.index[0], periods=2, freq=the_res)
    old_res = the_df.index[1] - the_df.index[0]
    new_res = tmp_df[1] - tmp_df[0]
    if new_res > old_res:  # Downsampling
        return the_df.resample(the_res).mean()
    elif new_res < old_res:  # Upsampling
        return the_df.resample(the_res).pad()
    else:
        return the_df


def initialise_market_data():
    """Initialise market data, TODO: broken, needs a little work"""

    print("Processing EPEX market data ...")

    df = pd.read_csv(
        "%s/%s" % (path_to_input_data, prices_filename),
        index_col=0,
        parse_dates=True,
        names={"EPEX_DA"},
    )
    df = set_datetime_index(df, freq="1H", timezone=pytz.timezone("Asia/Seoul"))
    market_type = MarketType.query.filter_by(name="day_ahead").one_or_none()

    res_df = timeseries_resample(
        df, "15T"
    )  # Sample time series for our target resolution
    market_count = 0
    for market_col_name in df:
        market_count += 1
        print("Processing market %s for resolution 15T ..." % market_col_name)
        market = Market.query.filter_by(
            name=market_col_name.lower(), market_type_name=market_type.name
        ).one_or_none()
        market_df = pd.DataFrame(index=res_df.index)
        market_df["y"] = res_df[market_col_name]

        market_df.to_pickle("%s/df_%s_res15T.pickle" % (path_to_pickles, market.name))


def initialise_weather_data():
    """Initialise weather data"""

    print("Processing weather data ...")

    df = pd.read_excel(
        "%s/%s" % (path_to_input_data, weather_excel_filename),
        "0_Weather",
        usecols=[0, 6, 14, 38],
        header=[0, 1],
        index_col=0,
    )
    headers = ["temperature", "total_radiation", "wind_speed"]
    df = set_datetime_index(
        df,
        freq="15min",
        start=pd.datetime(year=2015, month=1, day=1),
        timezone=pytz.timezone("Asia/Seoul"),
    )
    df = df[:-1]  # we got one row too many (of 2016)

    for i, weather_col_name in enumerate(df):
        res_df = timeseries_resample(
            df, "15T"
        )  # Sample time series for our target resolution
        weather_df = pd.DataFrame(index=res_df.index)
        weather_df["y"] = res_df[weather_col_name]
        weather_df.to_pickle("%s/df_%s_res15T.pickle" % (path_to_pickles, headers[i]))


def initialise_buildings_data():
    """Initialise building data"""

    print("Processing building data ...")

    df = pd.read_csv(
        "%s/%s" % (path_to_input_data, buildings_filename),
        index_col=0,
        parse_dates=True,
    )
    df = set_datetime_index(
        df, freq="1H", start=df.index[0], timezone=pytz.timezone("Asia/Seoul")
    )
    asset_type = AssetType.query.filter_by(name="building").one_or_none()

    asset_count = 0
    for asset_col_name in df:
        asset_name = asset_col_name.replace(" ", "_").lower()
        asset = Asset.query.filter_by(
            name=asset_name, asset_type_name=asset_type.name
        ).one_or_none()
        asset_count += 1
        print(
            "Processing building %s (%d/%d) for resolution 15T ..."
            % (asset.name, asset_count, len(df.columns))
        )
        res_df = timeseries_resample(
            df, "15T"
        )  # Sample time series for our target resolution
        asset_df = pd.DataFrame(index=res_df.index)
        asset_df["y"] = res_df[asset_col_name]

        asset_df.y /= (
            -1000
        )  # turn positive to negative to match our model, adjust from kWh to MWh

        assert all(asset_df.y <= 0)

        asset_df.to_pickle("%s/df_%s_res15T.pickle" % (path_to_pickles, asset.name))


def initialise_charging_station_data():
    """Initialise EV data"""

    print("Processing EV data ...")

    df = pd.read_csv(
        "%s/%s" % (path_to_input_data, evs_filename), index_col=0, parse_dates=True
    )
    df = set_datetime_index(
        df,
        freq="15min",
        start=df.index[0].floor("min"),
        timezone=pytz.timezone("Asia/Seoul"),
    )
    asset_type = AssetType.query.filter_by(name="charging_station").one_or_none()

    asset_count = 0
    for asset_col_name in df:
        asset_name = asset_col_name.replace(" ", "_").lower()
        asset = Asset.query.filter_by(
            name=asset_name, asset_type_name=asset_type.name
        ).one_or_none()
        asset_count += 1
        print(
            "Processing EV %s (%d/%d) for resolution 15T ..."
            % (asset.name, asset_count, len(df.columns))
        )
        res_df = timeseries_resample(
            df, "15T"
        )  # Sample time series for our target resolution
        asset_df = pd.DataFrame(index=res_df.index)
        asset_df["y"] = res_df[asset_col_name]

        asset_df.y /= (
            -1000000
        )  # turn positive to negative to match our model, adjust from Wh to MWh

        assert all(asset_df.y <= 0)

        asset_df.to_pickle("%s/df_%s_res15T.pickle" % (path_to_pickles, asset.name))


def initialise_a1_data():
    """Initialise A1 asset data
    TODO: Better distribution of workload across CPUs?
          If this method gets passed the sheet name, we'd already have three larger jobs (cars, evs, wind)
          to distribute. Best would be to create one job per asset here (just collecting asset metadata),
          and let each asset be processed by an externally callable method.
          Then we'd read in the same data frame once per asset, but that is not the expensive part here -
          the forecasting is.
          See also https://github.com/nhoening/fjd/issues/12
          But the main problem is forecasting, and prophet actually nicely uses a computer's CPUs. Distribution
          makes sense if we can use multiple computers.
    """
    A1Sheet = collections.namedtuple("Sheet", "name asset_type")
    solar_asset_type = AssetType.query.filter_by(name="solar").one_or_none()
    wind_asset_type = AssetType.query.filter_by(name="wind").one_or_none()
    a1_sheets = [
        A1Sheet(name="1_PV_CS6X-295P", asset_type=solar_asset_type),
        A1Sheet(name="2_WT_Enercon E40 600-46", asset_type=wind_asset_type),
    ]

    def make_a1_datetime_index(a1df):
        """From A1's date/time representation, make a proper datetime index"""
        a1df["datetime"] = pd.date_range(
            start="2015-01-01",
            end="2015-12-31 23:45:00",
            freq="15T",
            tz=pytz.timezone("Asia/Seoul"),
        )
        # TODO: Maybe we actually will want to compute the datetime from the Time column ...
        # df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
        # df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
        return a1df.set_index("datetime").drop(["Month", "Day", "Hour", "Time"], axis=1)

    for sheet in a1_sheets:
        # read in excel sheet
        print(
            "Processing sheet %s (%d/%d) for %s assets ..."
            % (
                sheet.name,
                a1_sheets.index(sheet) + 1,
                len(a1_sheets),
                sheet.asset_type.name,
            )
        )
        df = pd.read_excel(
            "%s/%s" % (path_to_input_data, asset_excel_filename), sheet.name
        )
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_a1_datetime_index(df)

        asset_count = 0
        for asset_col_name in df:
            asset_name = asset_col_name.replace(" ", "_").lower()
            asset = Asset.query.filter_by(
                name=asset_name, asset_type_name=sheet.asset_type.name
            ).one_or_none()
            asset_count += 1
            print(
                "Processing asset %s (%d/%d) for resolution 15T ..."
                % (asset.name, asset_count, len(df.columns))
            )
            res_df = df.resample(
                "15T"
            ).mean()  # Sample time series for given resolution
            asset_df = pd.DataFrame(index=res_df.index)
            asset_df["y"] = res_df[asset_col_name]

            if sheet.asset_type.is_producer and not sheet.asset_type.is_consumer:
                assert all(asset_df.y >= 0)
            if sheet.asset_type.is_consumer and not sheet.asset_type.is_producer:
                assert all(asset_df.y <= 0)

            asset_df.to_pickle("%s/df_%s_res15T.pickle" % (path_to_pickles, asset.name))


def initialise_all():
    initialise_weather_data()
    initialise_buildings_data()
    initialise_market_data()
    initialise_charging_station_data()
    initialise_a1_data()


if __name__ == "__main__":
    """Initialise markets and assets"""

    import bvp.data.config as db_config  # noqa: E402
    from bvp.app import create as create_app  # noqa: E402

    db_config.configure_db_for(create_app())

    if os.getcwd().endswith(
        "scripts"
    ):  # if this script is being called from within the data/scripts directory
        path_to_input_data = "../../raw_data/time-series"
        path_to_pickles = "../../raw_data/pickles"

    initialise_all()
