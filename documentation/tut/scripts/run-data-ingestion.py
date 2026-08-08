#!/usr/bin/env python3
"""Run and verify the data-ingestion tutorial against a FlexMeasures server."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from pathlib import Path
from time import monotonic

from flexmeasures_client import FlexMeasuresClient

EXAMPLE_FILE_VALUES = [1.0, 3.0, 9.0, 8.0, 7.0, 10.0]
EXAMPLE_FILE_START = "2022-12-11T05:00:00+00:00"
EXAMPLE_FILE_DURATION = "PT6H"
EXPORT_VALUES = [4.2, 4.8, 5.1, 4.6]
EXPORT_START = "2022-12-12T05:00:00+00:00"
EXPORT_DURATION = "PT4H"


def parse_args() -> argparse.Namespace:
    """Parse connection details and tutorial parameters."""

    repository_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Upload example sensor data and verify that FlexMeasures stored it."
    )
    parser.add_argument(
        "--host", default=os.getenv("FLEXMEASURES_HOST", "localhost:5000")
    )
    parser.add_argument(
        "--ssl",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("FLEXMEASURES_SSL", "false").lower() == "true",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("FLEXMEASURES_EMAIL", "toy-user@flexmeasures.io"),
    )
    parser.add_argument(
        "--sensor-id",
        type=int,
        default=os.getenv("FLEXMEASURES_SENSOR_ID"),
        required=os.getenv("FLEXMEASURES_SENSOR_ID") is None,
    )
    parser.add_argument(
        "--unit", default=os.getenv("FLEXMEASURES_SENSOR_UNIT", "EUR/MWh")
    )
    parser.add_argument(
        "--resolution", default=os.getenv("FLEXMEASURES_SENSOR_RESOLUTION", "PT1H")
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=repository_root
        / "flexmeasures"
        / "ui"
        / "static"
        / "examples"
        / "sensors-data.xlsx",
    )
    parser.add_argument("--timeout", type=float, default=60)
    return parser.parse_args()


async def wait_for_values_and_verify(
    client: FlexMeasuresClient,
    *,
    sensor_id: int,
    start: str,
    duration: str,
    resolution: str,
    unit: str,
    expected_values: list[float],
    timeout: float,
) -> None:
    """Wait for synchronous or queued ingestion and verify the stored values."""

    deadline = monotonic() + timeout
    last_values: list[float] | None = None
    while monotonic() < deadline:
        sensor_data = await client.get_sensor_data(
            sensor_id=sensor_id,
            start=start,
            duration=duration,
            resolution=resolution,
            unit=unit,
        )
        last_values = sensor_data["values"]
        if last_values == expected_values:
            assert sensor_data["start"] == start
            assert sensor_data["duration"] == duration
            assert sensor_data["unit"] == unit
            return
        await asyncio.sleep(1)
    raise AssertionError(
        f"Expected {expected_values} for sensor {sensor_id}, got {last_values}."
    )


async def run_tutorial(args: argparse.Namespace) -> None:
    """Upload a spreadsheet and exported values, then verify both intervals."""

    if not args.file.is_file():
        raise FileNotFoundError(f"Example data file not found: {args.file}")

    scheme = "https" if args.ssl else "http"
    print(
        f"Preparing FlexMeasures client for {scheme}://{args.host} "
        f"as {args.email} (sensor {args.sensor_id}).",
        flush=True,
    )
    password = os.getenv("FLEXMEASURES_PASSWORD") or getpass.getpass(
        f"FlexMeasures password for {args.email}: "
    )
    client = FlexMeasuresClient(
        host=args.host,
        ssl=args.ssl,
        email=args.email,
        password=password,
    )
    try:
        # Start file upload example
        print(f"Uploading spreadsheet: {args.file}", flush=True)
        await client.post_sensor_data(
            sensor_id=args.sensor_id,
            file_path=str(args.file),
            belief_time_measured_instantly=True,
        )
        # End file upload example
        print("Spreadsheet upload accepted; verifying stored values ...", flush=True)
        await wait_for_values_and_verify(
            client,
            sensor_id=args.sensor_id,
            start=EXAMPLE_FILE_START,
            duration=EXAMPLE_FILE_DURATION,
            resolution=args.resolution,
            unit=args.unit,
            expected_values=EXAMPLE_FILE_VALUES,
            timeout=args.timeout,
        )
        print("Spreadsheet values verified.", flush=True)

        # Start export script example
        print(f"Uploading {len(EXPORT_VALUES)} exported meter values ...", flush=True)
        await client.post_sensor_data(
            sensor_id=args.sensor_id,
            start=EXPORT_START,
            duration=EXPORT_DURATION,
            values=EXPORT_VALUES,
            unit=args.unit,
        )
        # End export script example
        print("Exported values accepted; verifying stored values ...", flush=True)
        await wait_for_values_and_verify(
            client,
            sensor_id=args.sensor_id,
            start=EXPORT_START,
            duration=EXPORT_DURATION,
            resolution=args.resolution,
            unit=args.unit,
            expected_values=EXPORT_VALUES,
            timeout=args.timeout,
        )
        print("Exported meter values verified.", flush=True)
    finally:
        await client.close()

    print("Data-ingestion tutorial completed successfully.", flush=True)


if __name__ == "__main__":
    asyncio.run(run_tutorial(parse_args()))
