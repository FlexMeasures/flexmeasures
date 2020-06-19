"""Tests a small simulation against the BVP running on a server."""
from datetime import timedelta

from isodate import parse_datetime, parse_duration
import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset

from bvp.data.scripts.simulation_utils import (
    check_version,
    check_services,
    get_auth_token,
    get_connections,
    post_soc_with_target,
    get_device_message,
    set_scheme_and_naming_authority,
)


pd.set_option("display.max_columns", None)
"""
useful code for cleaning the database afterwards:
    delete from power where asset_id=62;
    update asset set (soc_datetime, soc_udi_event_id) = ('2015-01-01 00:00:00+00', 0) where id=62;
"""

# Setup
data_path = "../../../raw_data"
sim_starts = [
    "2015-01-01T09:00:00+09:00",
    "2015-04-01T09:00:00+09:00",
    "2015-07-01T09:00:00+09:00",
    "2015-10-01T09:00:00+09:00",
]
schedule_duration = timedelta(hours=24)
udi_event_start_id = 1
owner_id = 11
asset_ids = [62, 63, 64]  # fast, slow, smart
contract_types = ["Fast tariff", "Slow tariff", "Smart tariff"]
server = "localhost"

if server == "demo":
    host = "https://demo.a1-bvp.com"
elif server == "play":
    host = "https://play.a1-bvp.com"
elif server == "staging":
    host = "https://staging.a1-bvp.com"
else:
    host = "http://localhost:5000"

latest_version = check_version(host)
services = check_services(host, latest_version)
auth_token = get_auth_token(host, "test-prosumer@seita.nl", "qB7e9rk")
connections, connection_names = get_connections(
    host, latest_version, auth_token, include_names=True
)

# Create DataFrame with prices
fast_charging_prices = pd.DataFrame(
    data=173.8,
    columns=["Fast tariff (KRW/kWh)"],
    index=pd.date_range(start=parse_datetime(sim_starts[0]), periods=8760, freq="H"),
)
slow_charging_prices = pd.DataFrame(
    data=71.3,
    columns=["Slow tariff (KRW/kWh)"],
    index=pd.date_range(start=parse_datetime(sim_starts[0]), periods=8760, freq="H"),
)
smart_charging_prices = pd.read_csv(
    data_path + "/smart_charging_tariff.csv", header=None, names=["Smart tariff (KRW/kWh)"]
)
smart_charging_prices.index = slow_charging_prices.index
df = (
    pd.concat(
        [fast_charging_prices, slow_charging_prices, smart_charging_prices], axis=1
    )
    .resample("15T")
    .pad()
)

# Add some columns already for the simulated connection names
sim_connections = [
    f"{set_scheme_and_naming_authority(host)}:{owner_id}:{asset_id}"
    for asset_id in asset_ids
]
sim_connection_names = [
    connection_names[connections.index(sim_connection)]
    for sim_connection in sim_connections
]
for sim_connection_name in sim_connection_names:
    df[sim_connection_name] = np.nan

# Repeat for different seasons
udi_event_id = udi_event_start_id
for sim_start in sim_starts:
    udi_event_id = udi_event_id + 1

    # For every asset
    for asset_id in asset_ids:
        print(f"Posting flexibility constraints for asset {asset_id} from {sim_start} onwards.")
        post_soc_with_target(
            host, latest_version, auth_token,
            owner_id=owner_id,
            asset_id=asset_id,
            udi_event_id=udi_event_id,
            soc_datetime=parse_datetime(sim_start), soc_value=6,
            target_datetime=parse_datetime(sim_start) + schedule_duration, target_value=24,
            unit="kWh"
        )

# Wait for scheduling jobs
input(
    "Run all scheduling jobs, then press Enter to continue ...\n"
    "You can run this in another bvp-venv shell:\n\n"
    "flask run_worker --name 'Sim worker' --queue 'scheduling'\n"
)

# Repeat for different seasons
udi_event_id = udi_event_start_id
for sim_start in sim_starts:
    udi_event_id = udi_event_id + 1

    # For every asset
    for asset_id in asset_ids:

        # Get schedule
        print(f"Retrieving schedule for asset {asset_id} from {sim_start} onwards.")
        response = get_device_message(
            host,
            latest_version,
            auth_token,
            owner_id=owner_id,
            asset_id=asset_id,
            udi_event_id=udi_event_id,
            duration=schedule_duration,
        )
        schedule = response.json()["values"]
        duration = parse_duration(response.json()["duration"])
        resolution = duration / len(schedule)

        # Add schedule to DataFrame
        connection = f"{set_scheme_and_naming_authority(host)}:{owner_id}:{asset_id}"
        connection_name = connection_names[connections.index(connection)]
        schedule = response.json()["values"]
        index = pd.date_range(
            parse_datetime(sim_start),
            periods=len(schedule),
            freq=to_offset(resolution).freqstr,
        )
        df[connection_name].loc[index] = schedule

for connection_name, contract_type in zip(sim_connection_names, contract_types):

    # -0 and nan to 0
    df[connection_name] = df[connection_name].clip(lower=0).fillna(0)

    # Calculate costs
    df[contract_type + " costs (cumulative KRW)"] = (
        (df[connection_name] * df[contract_type + " (KRW/kWh)"]).cumsum().shift(1, fill_value=0)
    )

    # Rename power columns
    df.rename(columns={connection_name: connection_name + " power (MW)"}, inplace=True)

print(df)

for sim_start in sim_starts:
    index = pd.date_range(
        parse_datetime(sim_start),
        periods=len(schedule),
        freq=to_offset(resolution).freqstr,
    )
    # Save as CSV
    df.loc[index].to_csv(f"{data_path}/{sim_start}_results.csv")

    # Save as graph
    ax = df.loc[index].plot(
        y=["Fast tariff costs (cumulative KRW)", "Slow tariff costs (cumulative KRW)", "Smart tariff costs (cumulative KRW)"]
    )
    fig = ax.get_figure()
    fig.savefig(f"{data_path}/{sim_start}_costs_figure.pdf")

    ax = df.loc[index].plot(y=["Fast tariff (KRW/kWh)", "Slow tariff (KRW/kWh)", "Smart tariff (KRW/kWh)"])
    fig = ax.get_figure()
    fig.savefig(f"{data_path}/{sim_start}_price_figure.pdf")

# Save everything as CSV
df.to_csv(data_path + "/results.csv")
