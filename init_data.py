#!/usr/bin/env python

"""
Script for loading and pickling dataframes from the Excel Spreadsheet we got from A1 with 2015 data.
When we move to a database, this will change.
"""
import collections
import json
import pandas as pd

from models import Asset, resolutions
from forecasting import make_rolling_forecast
import models

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


if __name__ == "__main__":
    assets = []
    for sheet in sheets:
        # read in excel sheet
        print("Processing sheet %s (%d/%d) for %s assets ..." %
              (sheet.name, sheets.index(sheet) + 1, len(sheets), sheet.asset_type.name))
        df = pd.read_excel(excel_filename, sheet.name)
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_datetime_index(df)
        for res in resolutions:
            res_df = df.resample(res).mean()
            asset_count = 0
            for asset_col_name in df:
                asset_count += 1
                asset = Asset(name=asset_col_name, asset_type_name=sheet.asset_type.name, area_code=0)
                print("Processing asset %s (%d/%d) for resolution %s (%d/%d) ..."
                      % (asset.name, asset_count, len(df.columns), res, resolutions.index(res) + 1, len(resolutions)))
                asset_df = pd.DataFrame(index=res_df.index, columns=["actual", "yhat", "yhat_upper", "yhat_lower"])
                asset_df.actual = res_df[asset_col_name]
                predictions = make_rolling_forecast(asset_df.actual, sheet.asset_type)
                for conf in ["yhat", "yhat_upper", "yhat_lower"]:
                    asset_df[conf] = predictions[conf]
                asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))
                if res == resolutions[0]:
                    assets.append(asset)
    with open("data/assets.json", "w") as af:
        af.write(json.dumps([asset.to_dict() for asset in assets]))
