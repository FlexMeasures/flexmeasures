#!/usr/bin/env python

"""
Script for loading and pickling dataframes from the Excel Spreadsheet we got from A1 with 2015 data.
When we move to a database, this will change.
"""
import collections

import pandas as pd


excel_filename = "data/20171120_A1-VPP_DesignDataSetR01.xls"

resolutions = ["15T", "1h", "1d", "1w"]
confidences = ["95", "50", "5"]

Sheet = collections.namedtuple('Sheet', 'name type')
sheets = [
    Sheet(name="1_PV_CS6X-295P", type="pv"),
    #Sheet(name="2_WT_Enercon E40 600-346", type="wind"),
    #Sheet(name="4_Load", type="ev"),
]

# map names in the data to the names we want to use
asset_name_map = {
    "EJJ PV (MW)": "EJJ_pv",
    "HL PV (MW)": "HL_pv",
    "JC PV (MW)": "JS_pv",
    "PS PV (MW)": "PS_pv",
    "SS PV (MW)": "SS_pv"
}

def lookup_asset_name(column_name):
    if column_name in asset_name_map:
        return asset_name_map[column_name]
    return column_name


Asset = collections.namedtuple('Asset', 'name type areaCode')
assets = []

# We group assets by OR-connected queries
AssetQuery = collections.namedtuple('AssetQuery', 'attr val')
asset_groups = dict(
    renewables=(AssetQuery(attr="type", val="pv"), AssetQuery(attr="type", val="wind")),
    vehicles=(AssetQuery(attr="type", val="ev"))
)


def make_datetime_index(df):
    """From A1's date/time representation, make a proper datetime index"""
    df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
    # TODO: Maybe we actually will want to compute the datetime from the Time column ...
    #df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
    #df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
    df = df.set_index('datetime').drop(['Month', 'Day', 'Hour', 'Time'], axis=1)
    return df


if __name__ == "__main__":
    for sheet in sheets:
        # read in excel sheet
        print("Processing sheet %s for %s assets ..." % (sheet.name, sheet.type))
        df = pd.read_excel(excel_filename, sheet.name)
        df = df[:-1]  # we got one row too many (of 2016)
        df = make_datetime_index(df)
        for asset_col_name in df:
            asset = Asset(name=lookup_asset_name(asset_col_name), type=sheet.type, areaCode=0)
            print("Processing asset %s ..." % asset.name)
            for res in resolutions:
                asset_df = pd.DataFrame(index=df.index, columns=["actual"] + confidences)
                asset_df.actual = df[asset_col_name]
                # TODO: make or collect predictions
                asset_df.fillna(0., inplace=True)  # slow
                asset_df.to_pickle("data/pickles/df_%s_res%s.pickle" % (asset.name, res))
            assets.append(asset)
    # save assets.json
    # per asset, make a df and pickle it