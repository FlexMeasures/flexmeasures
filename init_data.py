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
from pandas.tseries.frequencies import to_offset

excel_filename = "data/20171120_A1-VPP_DesignDataSetR01.xls"


Sheet = collections.namedtuple('Sheet', 'name asset_type')
sheets = [
    Sheet(name="1_PV_CS6X-295P", asset_type=models.asset_types["solar"]),
    Sheet(name="2_WT_Enercon E40 600-46", asset_type=models.asset_types["wind"]),
    # Sheet(name="4_Load", asset_type=models.asset_types["ev"]),
]


def make_datetime_index(a1df):
    """From A1's date/time representation, make a proper datetime index"""
    a1df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
    # TODO: Maybe we actually will want to compute the datetime from the Time column ...
    # df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
    # df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
    return a1df.set_index('datetime').drop(['Month', 'Day', 'Hour', 'Time'], axis=1)


def timeseries_resample(df: pd.DataFrame, res: str) -> pd.DataFrame:
    """Sample time series for given resolution, using the mean for downsampling and a forward fill for upsampling"""

    # Both of these preferred methods (choose one) are not correctly supported yet in pandas 0:22:0
    # res_df = df.resample(res, how='mean', fill_method='pad')
    # res_df = df.resample(res).mean().pad()

    tmp_df = pd.date_range(df.index[0], periods=2, freq=res)
    old_res = df.index[1] - df.index[0]
    new_res = tmp_df[1] - tmp_df[0]
    if new_res > old_res:  # Downsampling
        return df.resample(res).mean()
    elif new_res < old_res:  # Upsampling
        return df.resample(res).pad()
    else:
        return df


if __name__ == "__main__":

    # Initialise market data
    markets = []
    print("Processing EPEX market data")
    df = pd.read_csv('data/German day-ahead prices 20140101-20160630.csv', index_col=0, parse_dates = True, names = {'y'})

    # Construct a new datetime index from the starting date and length of the data, and apply it
    ix = pd.DatetimeIndex(start=df.index[0], periods=len(df.index), freq='1H')
    df = pd.DataFrame(data=df.y.values, index=ix, columns={'EPEX_DA'})

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
            predictions = make_rolling_forecast(market_df.y, market_type)
            for conf in ["yhat", "yhat_upper", "yhat_lower"]:
                market_df[conf] = predictions[conf]
            market_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (market.name, res))
            if res == resolutions[0]:
                markets.append(market)
    with open("data/markets.json", "w") as af:
        af.write(json.dumps([market.to_dict() for market in markets]))


    # Todo: Initialise EV asset data
    input()

    # Initialise A1 asset data
    assets = []
    for sheet in sheets:
        # read in excel sheet
        print("Processing sheet %s (%d/%d) for %s assets ..." %
              (sheet.name, sheets.index(sheet) + 1, len(sheets), sheet.asset_type.name))
        df = pd.read_excel(excel_filename, sheet.name)
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_datetime_index(df)
        for res in resolutions:
            res_df = timeseries_resample(df, res)   # Sample time series for given resolution
            asset_count = 0
            for asset_col_name in df:
                asset_count += 1
                asset = Asset(name=asset_col_name, asset_type_name=sheet.asset_type.name, area_code=0)
                print("Processing asset %s (%d/%d) for resolution %s (%d/%d) ..."
                      % (asset.name, asset_count, len(df.columns), res, resolutions.index(res) + 1, len(resolutions)))
                asset_df = pd.DataFrame(index=res_df.index, columns=["y", "yhat", "yhat_upper", "yhat_lower"])
                asset_df.y = res_df[asset_col_name]
                predictions = make_rolling_forecast(asset_df.y, sheet.asset_type)
                for conf in ["yhat", "yhat_upper", "yhat_lower"]:
                    asset_df[conf] = predictions[conf]
                asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))
                if res == resolutions[0]:
                    assets.append(asset)
    with open("data/assets.json", "w") as af:
        af.write(json.dumps([asset.to_dict() for asset in assets]))
