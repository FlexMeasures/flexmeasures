#!/usr/bin/env python

"""
Read in asset meta data (e.g. display name, capacity, location) given by A1
and apply to our current version of assets.json, as best as possible

Call this from the main directory:

./scripts/apply_jeju_meta_data.py
"""

import json
import pandas as pd
from typing import Tuple, Optional


filename = "data/VPP_DesignDataSetR02_(Jeju_GPS_180219).xls"


def extract() -> pd.DataFrame:
    print("Extracting meta data ...")

    df = pd.read_excel(filename, "IndexTable", usecols=[1, 4, 5, 6, 8], skiprows=[0],
                       header=None, names=["asset_type", "display_name", "id", "capacity", "location"])
    df.set_index(df.id.str.lower(), inplace=True) 
    df.drop("id", axis=1, inplace=True)
    return df


def update_asset(asset: dict, display_name: str, capacity: Optional[float], location: Tuple[str, str]):
    if display_name is not None:
        asset["display_name"] = display_name
    if capacity is not None:
        asset["capacity_in_mw"] = capacity
    if location is not None:
        latitude, longitude = location
        if "location" in asset:
            del asset["location"]
        asset["latitude"] = float(latitude.strip())
        asset["longitude"] = float(longitude.strip())


matched_charging_stations = []


def update_assets(metadata: pd.DataFrame):
    print("Updating assets.json ...")
    with open('data/assets.json', 'r') as assets_json:
        assets = json.loads(assets_json.read())
        for asset_md_id in metadata.index:
            asset_md = metadata.loc[asset_md_id]
            for asset in assets:
                if asset["name"] == asset_md_id or asset["name"] == asset_md_id.replace("-", "_"):
                    print("Found %s (%s - it's a %s asset)" % (asset_md_id, asset_md.display_name, asset_md.asset_type))
                    update_asset(asset, asset_md.display_name, asset_md.capacity, asset_md.location)
                    break
            else:
                print("Could not find %s (%s)" % (asset_md_id, asset_md.asset_type))
                if asset_md.asset_type == "ChargingStation":
                    # manually find one
                    candidates = [a for a in assets if a["asset_type_name"] == "charging_station"
                                  and a["name"] not in matched_charging_stations]
                    if candidates:
                        print("Putting %s's name and location to %s" % (asset_md.display_name, candidates[0]["name"]))
                        update_asset(candidates[0], asset_md.display_name, None, asset_md.location)
                        matched_charging_stations.append(candidates[0]["name"])
    with open('data/assets.json', 'w') as assets_json:
        assets_json.write(json.dumps(assets, indent=True))


if __name__ == "__main__":
    df_metadata = extract()
    matched_charging_stations = []
    update_assets(df_metadata)
