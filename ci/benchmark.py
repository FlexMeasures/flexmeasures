#!/usr/bin/env python3
"""
This file is a script to run bench-marking tests for the FlexMeasures project.
It can be useful to compare two states, and see if performance has improved or got worse.

Call like this:

./ci/benchmark.py --iterations 5  --sensor 6 --sensor 7 --start 2023-01-01T05:00:00.000Z --duration P1M
"""

import subprocess
import time
import isodate
import numpy as np
import tqdm
import click

# TODO: do not use CLI, but the client (ask for credentials from input)
# from flexmeasures_client import Client as FlexMeasuresClient

from flexmeasures.data.schemas import DurationField, AwareDateTimeField


@click.command()
@click.option("--iterations", type=int, default=10)
@click.option("--sensor", "sensors", type=int, multiple=True, required=True)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(format="iso"),
    required=True,
    help="Start queries at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--duration",
    "duration",
    type=DurationField(),
    default="P30D",
    help="Duration of data to be queried, after --start. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
def benchmark(iterations, sensors, start, duration):
    """
    This command queries belief data a couple times and tells you how long that took on average (and the STD).
    """
    start_str = str(start).replace(" ", "T")
    start_str = isodate.datetime_isoformat(start)
    duration_str = isodate.strftime(duration, "P%P")
    sensor_ids = " ".join([f"--sensor-id {sensor_id}" for sensor_id in sensors])
    commands = [
        f"flexmeasures show beliefs {sensor_ids} --start {start_str} --duration {duration_str}",
        # TODO: add a scheduling operation (wait for result)
    ]

    print("I'll be running:")
    print("\n".join(commands))
    print()
    print(f"I'll repeat this {iterations} times.")
    print()

    timings = {}

    for idx, command in enumerate(commands):
        for _ in tqdm.tqdm(range(iterations)):
            start = time.perf_counter()
            run_command(command)
            stop = time.perf_counter()
            try:
                timings[idx].append(start - stop)
            except KeyError:
                timings[idx] = [start - stop]

    # Get mean and standard deviation of timings
    print(f"All timings are in seconds and iterated {iterations} times")
    for idx, timing in timings.items():
        print(f"Command {commands[idx]}: {np.mean(timing)} ± {np.std(timing)}")


def run_command(command):
    # Run command using subprocess and check for errors but don't print output
    try:
        subprocess.run(command, shell=True, check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as process_error:
        print(process_error)
        exit(1)


if __name__ == "__main__":
    benchmark()
