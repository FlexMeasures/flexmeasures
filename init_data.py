#!/usr/bin/env python

"""
Script for loading and pickling dataframes from the Excel Spreadsheet we got from A1 with 2015 data.
When we move to a database, this will change.
"""
import collections
import json

import pandas as pd

from models import Asset


excel_filename = "data/20171120_A1-VPP_DesignDataSetR01.xls"

resolutions = ["15T", "1h", "1d", "1w"]
confidences = ["95", "50", "5"]

Sheet = collections.namedtuple('Sheet', 'name type')
sheets = [
    Sheet(name="1_PV_CS6X-295P", type="solar"),
    Sheet(name="2_WT_Enercon E40 600-46", type="wind"),
    # Sheet(name="4_Load", type="ev"),
]

assets = []


def make_datetime_index(a1df):
    """From A1's date/time representation, make a proper datetime index"""
    a1df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
    # TODO: Maybe we actually will want to compute the datetime from the Time column ...
    # df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
    # df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
    return a1df.set_index('datetime').drop(['Month', 'Day', 'Hour', 'Time'], axis=1)


if __name__ == "__main__":
    for sheet in sheets:
        # read in excel sheet
        print("Processing sheet %s for %s assets ..." % (sheet.name, sheet.type))
        df = pd.read_excel(excel_filename, sheet.name)
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_datetime_index(df)
        for asset_col_name in df:
            asset = Asset(name=asset_col_name, resource_type=sheet.type, area_code=0)
            print("Processing asset %s ..." % asset.name)
            for res in resolutions:
                asset_df = pd.DataFrame(index=df.index, columns=["actual"] + confidences)
                asset_df.actual = df[asset_col_name]
                # TODO: make or collect predictions
                asset_df.fillna(0., inplace=True)  # this is slow
                # if we forecast on the actual resolution, we'll need to start the df already resampled.
                asset_df = asset_df.resample(res).mean()
                asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))
            assets.append(asset)
        with open("data/assets.json", "w") as af:
            af.write(json.dumps([asset.to_dict() for asset in assets]))
