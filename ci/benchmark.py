#!/usr/bin/env python3
# This file is a script to run the benchmarking tests for the project.

import subprocess
import time
import numpy as np
import tqdm


def main():
    commands = [
        "flexmeasures show beliefs --sensor-id 6 --sensor-id 16 --sensor-id 15 --sensor-id 8 --sensor-id 5 --sensor-id 4 --start 2023-01-01T05:00:00.000Z --duration P0Y0M1D",
        "flexmeasures show beliefs --sensor-id 6 --sensor-id 16 --sensor-id 15 --sensor-id 8 --sensor-id 5 --sensor-id 4 --start 2023-01-01T05:00:00.000Z --duration P0Y0M30D",
        "flexmeasures show beliefs --sensor-id 6 --sensor-id 16 --sensor-id 15 --sensor-id 8 --sensor-id 5 --sensor-id 4 --start 2023-01-01T05:00:00.000Z --duration P0Y0M60D",
    ]

    timings = {}
    max_iterations = 10

    for idx, command in enumerate(commands):
        for _ in tqdm.tqdm(range(max_iterations)):
            start = time.perf_counter()
            run_command(command)
            stop = time.perf_counter()
            try:
                timings[idx].append(start - stop)
            except KeyError:
                timings[idx] = [start - stop]

    # Get mean and standard deviation of timings
    print(f"All timings are in seconds and iterated {max_iterations} times")
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
    main()
