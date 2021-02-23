from datetime import datetime, timedelta

import pytest
import pytz
import isodate

from flexmeasures.api.common.schemas.times import DurationField, DurationValidationError


@pytest.mark.parametrize(
    "duration_input,exp_deserialization",
    [
        ("PT1H", timedelta(hours=1)),
        ("PT6M", timedelta(minutes=6)),
        ("PT6H", timedelta(hours=6)),
        ("P2DT1H", timedelta(hours=49)),
    ],
)
def test_duration_field_straightforward(duration_input, exp_deserialization):
    """Testing straightforward cases"""
    df = DurationField()
    deser = df.deserialize(duration_input, None, None)
    assert deser == exp_deserialization
    assert df.serialize("duration", {"duration": deser}) == duration_input


@pytest.mark.parametrize(
    "duration_input,exp_deserialization,grounded_timedelta",
    [
        ("P1M", isodate.Duration(months=1), timedelta(days=29)),
        ("PT24H", isodate.Duration(hours=24), timedelta(hours=24)),
        ("P2D", isodate.Duration(hours=48), timedelta(hours=48)),
        # following are calendar periods including a transition to daylight saving time (DST)
        ("P2M", isodate.Duration(months=2), timedelta(days=60) - timedelta(hours=1)),
        # ("P8W", isodate.Duration(days=7*8), timedelta(weeks=8) - timedelta(hours=1)),
        # ("P100D", isodate.Duration(days=100), timedelta(days=100) - timedelta(hours=1)),
        # following is a calendar period with transitions to DST and back again
        ("P1Y", isodate.Duration(years=1), timedelta(days=366)),
    ],
)
def test_duration_field_nominal_grounded(
    duration_input, exp_deserialization, grounded_timedelta
):
    """Nominal durations are tricky:
    https://en.wikipedia.org/wiki/Talk:ISO_8601/Archive_2#Definition_of_Duration_is_incorrect
    We want to test if we can ground them as expected.
    We use a particular datetime to ground, in a leap year February.
    For the Europe/Amsterdam timezone, daylight saving time started on March 29th 2020.
    # todo: the commented out tests would work if isodate.parse_duration would have the option to stop coercing ISO 8601 days into datetime.timedelta days
    """
    df = DurationField()
    deser = df.deserialize(duration_input, None, None)
    assert deser == exp_deserialization
    dummy_time = pytz.timezone("Europe/Amsterdam").localize(
        datetime(2020, 2, 22, 18, 7)
    )
    grounded = DurationField.ground_from(deser, dummy_time)
    assert grounded == grounded_timedelta


@pytest.mark.parametrize(
    "duration_input,error_msg",
    [
        ("", "Unable to parse duration string"),
        ("1H", "Unable to parse duration string"),
        ("PP1M", "time designator 'T' missing"),
        ("PT2D", "Unrecognised ISO 8601 date format"),
    ],
)
def test_duration_field_invalid(duration_input, error_msg):
    df = DurationField()
    with pytest.raises(DurationValidationError) as ve:
        df.deserialize(duration_input, None, None)
    assert error_msg in str(ve)
