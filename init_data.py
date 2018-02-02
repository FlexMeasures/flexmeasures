#!/usr/bin/env python

"""
Script for loading and pickling dataframes from the Excel Spreadsheet we got from A1 with 2015 data.
When we move to a database, this will change.
"""
import collections
import json
import pandas as pd

from models import Asset, Market, resolutions
from forecasting import make_rolling_forecast
import models


asset_excel_filename = "data/20171120_A1-VPP_DesignDataSetR01.xls"
prices_filename = 'data/German day-ahead prices 20140101-20160630.csv'
evs_filename = 'data/German charging stations 20150101-20150620.csv'


Sheet = collections.namedtuple('Sheet', 'name asset_type')
sheets = [
    Sheet(name="1_PV_CS6X-295P", asset_type=models.asset_types["solar"]),
    Sheet(name="2_WT_Enercon E40 600-46", asset_type=models.asset_types["wind"])
]


def make_datetime_index(a1df):
    """From A1's date/time representation, make a proper datetime index"""
    a1df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
    # TODO: Maybe we actually will want to compute the datetime from the Time column ...
    # df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
    # df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
    return a1df.set_index('datetime').drop(['Month', 'Day', 'Hour', 'Time'], axis=1)


def set_datetime_index(old_df: pd.DataFrame, freq: str, start=None) -> pd.DataFrame:
    """Construct a new datetime index from the starting date and length of the data, and apply it"""
    if start is None:
        ix = pd.DatetimeIndex(start=old_df.index[0], periods=len(old_df.index), freq=freq)
    else:
        ix = pd.DatetimeIndex(start=start, periods=len(old_df.index), freq=freq)
    new_df = pd.DataFrame(data=old_df.to_dict(orient='records'), index=ix)
    return new_df


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


def write_asset_to_list(new_asset: Asset):
    """Add a new asset to the list of existing assets on file.
    This can go wrong if the method is called twice in short order, of course.
    However, we compute forecasts per asset at length, so we decide it is a non-issue
    until we get bitten and reactor.
    The advantage is that assets.json always reflects what is pickled right now - so while
    pickles are re-made, the app might still function."""
    asset_dicts = []
    with open("data/assets.json", "r") as af:
        assets_str = af.read()
        if assets_str != "":
            asset_dicts += json.loads(assets_str)
    # If asset (by name) exists, drop it.
    asset_dicts_wo_asset = [ad for ad in asset_dicts if ad["name"] != new_asset.name]
    asset_dicts_wo_asset.append(new_asset.to_dict())
    with open("data/assets.json", "w") as af:
        af.write(json.dumps(asset_dicts_wo_asset))


def initialise_market_data():
    """Initialise market data"""

    print("Processing EPEX market data ...")
    markets = []

    df = pd.read_csv(prices_filename, index_col=0, parse_dates=True, names={'EPEX_DA'})
    df = set_datetime_index(df, freq='1H')
    market_type = models.market_types['day_ahead']

    for res in resolutions:
        res_df = timeseries_resample(df, res)  # Sample time series for given resolution
        market_count = 0
        for market_col_name in df:
            market_count += 1
            market = Market(name=market_col_name, market_type_name=market_type.name)
            print("Processing market %s (%d/%d) for resolution %s (%d/%d) ..."
                  % (market.name, market_count, len(df.columns), res, resolutions.index(res) + 1, len(resolutions)))
            market_df = pd.DataFrame(index=res_df.index, columns=["y", "yhat", "yhat_upper", "yhat_lower"])
            market_df.y = res_df[market_col_name]

            # Run forecasts (the heavy computation) and save them
            forecasts, horizons = make_rolling_forecast(market_df.y, market_type, res)
            for h in horizons:
                for forecast_result in ["yhat_%s" % h, "yhat_%s_upper" % h, "yhat_%s_lower" % h]:
                    market_df[forecast_result] = forecasts[forecast_result]
            market_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (market.name, res))

            if res == resolutions[-1]:
                markets.append(market)
    with open("data/markets.json", "w") as af:
        af.write(json.dumps([market.to_dict() for market in markets]))


def initialise_ev_data():
    """Initialise EV data"""

    print("Processing EV data ...")

    df = pd.read_csv(evs_filename, index_col=0, parse_dates=True)
    df = set_datetime_index(df, freq='15min', start=df.index[0].floor('min'))
    asset_type = models.asset_types['ev']

    asset_count = 0
    for asset_col_name in df:
        asset = Asset(name=asset_col_name, asset_type_name=asset_type.name)
        asset_count += 1
        for res in resolutions:
            print("Processing EV %s (%d/%d) for resolution %s (%d/%d) ..."
                  % (asset.name, asset_count, len(df.columns), res, resolutions.index(res) + 1, len(resolutions)))
            res_df = timeseries_resample(df, res)  # Sample time series for given resolution
            asset_df = pd.DataFrame(index=res_df.index, columns=["y", "yhat", "yhat_upper", "yhat_lower"])
            asset_df.y = res_df[asset_col_name]

            asset_df.y /= -1000000  # turn positive to negative to match our model, adjust from Wh to MWh

            assert(all(asset_df.y <= 0))

            # Run forecasts (the heavy computation) and save them
            forecast, horizons = make_rolling_forecast(asset_df.y, asset_type, res)
            for h in horizons:
                for forecast_result in ["yhat_%s" % h, "yhat_%s_upper" % h, "yhat_%s_lower" % h]:
                    asset_df[forecast_result] = forecast[forecast_result]
            asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))

        write_asset_to_list(asset)


def initialise_a1_data():
    """Initialise A1 asset data
    TODO: if this method gets passed the sheet name, we'd already have three larger jobs (cars, evs, wind)
          to distribute. Best would be to create one job per asset here (just collecting asset metadata),
          and let each asset be processed by an externally callable method.
          Then we'd read in the same data frame once per asset, but that is not the expensive part here -
          the forecasting is.
          See also https://github.com/nhoening/fjd/issues/12
    """

    for sheet in sheets:
        # read in excel sheet
        print("Processing sheet %s (%d/%d) for %s assets ..." %
              (sheet.name, sheets.index(sheet) + 1, len(sheets), sheet.asset_type.name))
        df = pd.read_excel(asset_excel_filename, sheet.name)
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_datetime_index(df)

        asset_count = 0
        for asset_col_name in df:
            asset = Asset(name=asset_col_name, asset_type_name=sheet.asset_type.name, area_code=0)
            asset_count += 1
            for res in resolutions:
                print("Processing asset %s (%d/%d) for resolution %s (%d/%d) ..."
                      % (asset.name, asset_count, len(df.columns), res, resolutions.index(res) + 1, len(resolutions)))
                res_df = df.resample(res).mean()  # Sample time series for given resolution
                asset_df = pd.DataFrame(index=res_df.index, columns=["y", "yhat", "yhat_upper", "yhat_lower"])
                asset_df.y = res_df[asset_col_name]

                if sheet.asset_type.is_producer and not sheet.asset_type.is_consumer:
                    assert(all(asset_df.y >= 0))
                if sheet.asset_type.is_consumer and not sheet.asset_type.is_producer:
                    assert(all(asset_df.y <= 0))

                # Run forecasts (the heavy computation) and save them
                forecast, horizons = make_rolling_forecast(asset_df.y, sheet.asset_type, res)
                for h in horizons:
                    for forecast_result in ["yhat_%s" % h, "yhat_%s_upper" % h, "yhat_%s_lower" % h]:
                        asset_df[forecast_result] = forecast[forecast_result]
                asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))

            write_asset_to_list(asset)


if __name__ == "__main__":
    """Initialise markets and assets"""

    initialise_market_data()

    initialise_ev_data()
    initialise_a1_data()
