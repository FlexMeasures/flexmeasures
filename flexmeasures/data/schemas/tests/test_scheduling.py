from datetime import datetime
import pytz
import pytest

import pandas as pd

from flexmeasures.data.schemas.scheduling.process import (
    ProcessSchedulerFlexModelSchema,
    ProcessType,
)
from flexmeasures.data.schemas.scheduling.storage import SOCValueSchema


@pytest.mark.parametrize(
    "timing_input",
    [
        {"datetime": "2023-03-27T00:00:00+00:00"},
        {"start": "2023-03-26T00:00:00+00:00", "end": "2023-03-27T00:00:00+00:00"},
        {"start": "2023-03-26T00:00:00+00:00", "duration": "PT24H"},
        {"end": "2023-03-27T00:00:00+00:00", "duration": "PT24H"},
    ],
)
def test_soc_value_field(timing_input):
    data = SOCValueSchema().load(
        {
            "value": 3,
            **timing_input,
        }
    )
    print(data)
    assert data["end"] == pd.Timestamp("2023-03-27T00:00:00+00:00")


def test_process_scheduler_flex_model_load(db, app, setup_dummy_sensors):

    sensor1, _ = setup_dummy_sensors

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.INFLEXIBLE


def test_process_scheduler_flex_model_process_type(db, app, setup_dummy_sensors):

    sensor1, _ = setup_dummy_sensors

    # checking default

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.INFLEXIBLE

    sensor1.attributes["process-type"] = "SHIFTABLE"

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.SHIFTABLE
