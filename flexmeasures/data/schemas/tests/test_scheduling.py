from flexmeasures.data.schemas.scheduling.shiftable_load import (
    ShiftableLoadFlexModelSchema,
    LoadType,
)

from datetime import datetime
import pytz


def test_shiftable_load_flex_model_load(db, app, setup_dummy_sensors):

    sensor1, _ = setup_dummy_sensors

    schema = ShiftableLoadFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    shiftable_load_flex_model = schema.load(
        {
            "cost-sensor": sensor1.id,
            "duration": "PT4H",
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    print(shiftable_load_flex_model)


def test_shiftable_load_flex_model_load_type(db, app, setup_dummy_sensors):

    sensor1, _ = setup_dummy_sensors

    # checking default

    schema = ShiftableLoadFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    shiftable_load_flex_model = schema.load(
        {
            "cost-sensor": sensor1.id,
            "duration": "PT4H",
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert shiftable_load_flex_model["load_type"] == LoadType.INFLEXIBLE

    sensor1.attributes["load_type"] = "SHIFTABLE"

    schema = ShiftableLoadFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    shiftable_load_flex_model = schema.load(
        {
            "duration": "PT4H",
            "cost-sensor": sensor1.id,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert shiftable_load_flex_model["load_type"] == LoadType.SHIFTABLE
