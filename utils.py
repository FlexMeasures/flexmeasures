import datetime

import pandas as pd


# global data source, will be replaced by DB connection probably
PV_DATA = None


def get_solar_data(solar_asset:str, month:int, day:int):
    global PV_DATA
    if PV_DATA is None:
        df = pd.read_csv("data/pv.csv")
        df['datetime'] = pd.date_range(start="2015-01-01", end="2015-12-31 23:45:00", freq="15T")
        # TODO: Maybe we actually will want to compute the datetime from the Time column ...
        #df["Seconds_In_2015"] = df.Time * 4 * 15 * 60
        #df['datetime'] = pd.to_datetime(df.Seconds_In_2015, origin=datetime.datetime(year=2015, month=1, day=1), unit="s")
        df = df.set_index('datetime').drop(['Month', 'Day', 'Time'], axis=1)
        PV_DATA = df

    start = datetime.datetime(year=2015, month=month, day=day)
    end = start + datetime.timedelta(days=1)
    date_range_mask = (PV_DATA.index >= start) & (PV_DATA.index < end)
    return PV_DATA.loc[date_range_mask][solar_asset]


