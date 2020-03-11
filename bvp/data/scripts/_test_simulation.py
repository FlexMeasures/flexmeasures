"""Tests a small simulation against the BVP running on a server."""
from datetime import timedelta
import time

from isodate import parse_datetime

from bvp.data.scripts.simulation_utils import (
    check_version,
    check_services,
    get_PA_token,
    get_auth_token,
    get_connections,
    get_cpu_seconds,
    post_meter_data,
    post_price_forecasts,
    post_weather_forecasts,
)


# Setup
server = "staging"
num_days_sim = 140
batch_size = 96  # number of 15-minute meter readings sent in one POST request (we recommend 96, i.e. daily batches)
automate_simulation = True
seconds_of_sleep_between_steps = (
    61  # Python Anywhere recommends > 60 (due to CPU budget update frequency)
)

if server == "play":
    host = "https://play.a1-bvp.com"
elif server == "staging":
    host = "https://staging.a1-bvp.com"
else:
    host = "http://localhost:5000"
PA_API_TOKEN = get_PA_token()

latest_version = check_version(host)
services = check_services(host, latest_version)
auth_token = get_auth_token(host)
connections = get_connections(host, latest_version, auth_token)

# Initialisation
num_days_init = 50
sim_start = "2050-01-01T00:00:00+09:00"
post_price_forecasts(
    host,
    latest_version,
    auth_token,
    start=parse_datetime(sim_start),
    num_days=num_days_init + num_days_sim,
)
post_weather_forecasts(
    host,
    latest_version,
    auth_token,
    start=parse_datetime(sim_start),
    num_days=num_days_init + num_days_sim,
)
post_meter_data(
    host,
    latest_version,
    auth_token,
    start=parse_datetime(sim_start),
    batch_size=num_days_init * 96,
    connection=connections[1],
)

if automate_simulation is False:
    input(
        f"Finished initialising simulation on {server}."
        f"Go to {host}/rq/forecasting to check forecasting jobs have been created."
        f"Assign a worker to process these jobs, then press Enter to continue ...\n"
        "You can run a local worker in another bvp-venv shell:\n\n"
        'flask run-worker --name "RQ worker [SIM]" --queue "forecasting"\n\n'
        f"Or assign a continuous task on PA on work on {server}:\n\n"
        f'go {server} && flask run-worker --name "RQ worker [SIM]" --queue "forecasting"\n\n'
    )
else:
    time.sleep(seconds_of_sleep_between_steps)

# Simulation steps
for i in range(num_days_sim * 96 // batch_size):
    if automate_simulation is False:
        print("Sending batch %s out of %s" % (i + 1, num_days_sim * 96 // batch_size))

    # post_weather_data(
    #     host,
    #     latest_version,
    #     auth_token,
    #     start=parse_datetime(sim_start) + timedelta(days=num_days_init + i),
    #     num_days=1,
    # )
    post_meter_data(
        host,
        latest_version,
        auth_token,
        start=parse_datetime(sim_start)
        + timedelta(days=num_days_init, seconds=i * batch_size * 15 * 60),
        batch_size=batch_size,  # send meter data in batches of a certain size, e.g. 96 values sent every 24 hours
        connection=connections[1],
    )

    # Run forecasting jobs
    cpu_seconds_before, cpu_seconds_budget = get_cpu_seconds(
        "seita", PA_API_TOKEN
    )  # Track CPU time spent
    if automate_simulation is False:
        input(
            f"Finished sending simulation to {server}. "
            f"Go to {host}/rq/forecasting to check forecasting jobs have been created. "
            f"Assign a worker to process these jobs, wait at least 60 seconds for CPU seconds budget on PA to update, then press Enter to continue ...\n"
            "You can run a local worker in another bvp-venv shell:\n\n"
            'flask run-worker --name "RQ worker [SIM]" --queue "forecasting"\n\n'
            f"Or assign a continuous task on PA on work on {server}:\n\n"
            f'go {server} && flask run-worker --name "RQ worker [SIM]" --queue "forecasting"\n\n'
        )
    else:
        time.sleep(seconds_of_sleep_between_steps)
    cpu_seconds_after, _ = get_cpu_seconds("seita", PA_API_TOKEN)
    print(
        f"Batch {i+1} out of {num_days_sim * 96 // batch_size} - CPU seconds spent on forecasting: "
        f"{round(cpu_seconds_after - cpu_seconds_before, 3)} out of {cpu_seconds_budget}"
    )

print(
    f"Don't forget to delete your simulation results from the {server} database! Using:\n\n"
    f"delete from power where datetime > '2049-12-30';\n"
    f"delete from price where datetime > '2049-12-30';\n"
    f"delete from weather where datetime > '2049-12-30';\n"
)
