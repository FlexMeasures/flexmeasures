from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytz
import isodate

from flexmeasures.data.schemas.times import (
    DurationField,
    DurationValidationError,
    NominalDurationField,
    ResolutionField,
    needs_a_calendar,
)


@pytest.mark.parametrize(
    "duration_input, exp_deserialization",
    [
        ("PT1H", timedelta(hours=1)),
        ("PT6M", timedelta(minutes=6)),
        ("PT6H", timedelta(hours=6)),
        ("P2DT1H", timedelta(hours=49)),  # https://github.com/gweis/isodate/issues/74
    ],
)
def test_duration_field_straightforward(duration_input, exp_deserialization):
    """Testing straightforward cases"""
    df = DurationField()
    deser = df.deserialize(duration_input, None, None)
    assert deser == exp_deserialization
    assert df.serialize("duration", {"duration": deser}) == duration_input


@pytest.mark.parametrize(
    "duration_input, exp_deserialization, grounded_timedelta",
    [
        ("P1M", isodate.Duration(months=1), timedelta(days=29)),
        ("PT24H", isodate.Duration(hours=24), timedelta(hours=24)),
        ("P2D", isodate.Duration(hours=48), timedelta(hours=48)),
        # following are calendar periods including a transition to daylight saving time (DST)
        ("P2M", isodate.Duration(months=2), timedelta(days=60) - timedelta(hours=1)),
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
    "duration_input, error_msg",
    [
        ("", "Unable to parse duration string"),
        ("1H", "Unable to parse duration string"),
        ("PP1M", "time designator 'T' missing"),
        ("PT2D", "Unrecognised ISO 8601 date format"),
        ("PT40S", "FlexMeasures only support multiples of 1 minute."),
    ],
)
def test_duration_field_invalid(duration_input, error_msg):
    df = DurationField()
    with pytest.raises(DurationValidationError) as ve:
        df.deserialize(duration_input, None, None)
    assert error_msg in str(ve)


@pytest.mark.parametrize(
    "resolution_input, exp_deserialization",
    [
        ("PT15M", timedelta(minutes=15)),
        ("PT1H", timedelta(hours=1)),
        ("P1D", timedelta(days=1)),
        ("P1M", isodate.Duration(months=1)),
        # a nominal duration holds its days and seconds in its tdelta, not next to it.
        ("P1M1D", isodate.Duration(months=1, days=1)),
        ("P1Y1D", isodate.Duration(years=1, days=1)),
        ("P1MT1H", isodate.Duration(months=1, hours=1)),
    ],
)
def test_resolution_field_positive(resolution_input, exp_deserialization):
    """A resolution spanning a positive amount of time deserializes like any other duration."""
    rf = ResolutionField()
    assert rf.deserialize(resolution_input, None, None) == exp_deserialization


@pytest.mark.parametrize(
    "resolution_input",
    [
        "PT0S",
        "PT0M",
        "P0D",
        "-PT15M",
        "-P1D",
        "-P1M",
        "-P1M1D",
    ],
)
def test_resolution_field_not_positive(resolution_input):
    """A resolution that does not span a positive amount of time is rejected.

    Without this validation, a zero resolution would crash the API with a ZeroDivisionError,
    and a negative resolution would silently describe an empty set of events.
    """
    rf = ResolutionField()
    with pytest.raises(DurationValidationError) as ve:
        rf.deserialize(resolution_input, None, None)
    assert "FlexMeasures only supports a positive resolution" in str(ve)


def test_resolution_field_still_validates_duration():
    """A resolution is still subject to the validation that any duration is subject to."""
    rf = ResolutionField()
    with pytest.raises(DurationValidationError) as ve:
        rf.deserialize("PT40S", None, None)
    assert "FlexMeasures only support multiples of 1 minute." in str(ve)


# Daylight saving time in Europe/Amsterdam started on 2020-03-29 and 2023-03-26,
# and ended on 2023-10-29.
@pytest.mark.parametrize(
    "duration_input, start, exp_grounded",
    [
        # a fixed duration stays fixed, even across a transition.
        ("PT24H", "2023-03-26T00:00:00+01:00", timedelta(hours=24)),
        ("PT168H", "2023-03-26T00:00:00+01:00", timedelta(hours=168)),
        # a calendar duration follows the calendar, so it loses an hour going into DST.
        ("P1D", "2023-03-26T00:00:00+01:00", timedelta(hours=23)),
        ("P1W", "2023-03-26T00:00:00+01:00", timedelta(days=7) - timedelta(hours=1)),
        ("P8W", "2020-02-22T18:07:00+01:00", timedelta(weeks=8) - timedelta(hours=1)),
        (
            "P100D",
            "2020-02-22T18:07:00+01:00",
            timedelta(days=100) - timedelta(hours=1),
        ),
        ("P1M", "2020-02-22T18:07:00+01:00", timedelta(days=29)),
        ("P1Y", "2020-02-22T18:07:00+01:00", timedelta(days=366)),
        # and gains one coming back out of it.
        ("P1D", "2023-10-29T00:00:00+02:00", timedelta(hours=25)),
        # a duration mixing the two counts each part in its own way.
        ("P1DT1H", "2023-03-26T00:00:00+01:00", timedelta(hours=24)),
        # away from a transition, both kinds agree.
        ("P1D", "2023-06-01T00:00:00+02:00", timedelta(hours=24)),
    ],
)
def test_nominal_duration_field_grounding(duration_input, start, exp_grounded):
    """A calendar duration is counted against the sensor's calendar, a fixed one is not.

    Note that isodate reports "P1D" and "PT24H" as the same duration,
    so this distinction is drawn by NominalDurationField itself.
    """
    deser = NominalDurationField().deserialize(duration_input, None, None)
    grounded = DurationField.ground_from(
        deser, isodate.parse_datetime(start), timezone="Europe/Amsterdam"
    )
    assert grounded == exp_grounded


def test_nominal_duration_field_needs_a_timezone_to_count_in():
    """Without a timezone, a calendar duration is counted against the start's own UTC offset.

    An offset never shifts, so every calendar day comes out as 24 hours.
    """
    deser = NominalDurationField().deserialize("P1D", None, None)
    start = isodate.parse_datetime("2023-03-26T00:00:00+01:00")
    assert DurationField.ground_from(deser, start) == timedelta(hours=24)
    assert DurationField.ground_from(
        deser, start, timezone="Europe/Amsterdam"
    ) == timedelta(hours=23)


def test_nominal_duration_field_leaves_fixed_durations_alone():
    """A duration with no calendar component deserializes to a plain timedelta."""
    field = NominalDurationField()
    assert field.deserialize("PT24H", None, None) == timedelta(hours=24)
    assert field.deserialize("PT30M", None, None) == timedelta(minutes=30)
    # a fraction of a calendar unit has no calendar meaning, so it is read as fixed time.
    assert field.deserialize("P0.5D", None, None) == timedelta(hours=12)


def test_nominal_duration_field_still_validates_duration():
    """A calendar duration is still subject to the validation that any duration is subject to."""
    with pytest.raises(DurationValidationError) as ve:
        NominalDurationField().deserialize("P1DT40S", None, None)
    assert "FlexMeasures only support multiples of 1 minute." in str(ve)


@pytest.mark.parametrize(
    "tzinfo_flavour",
    ["pytz", "zoneinfo", "fixed-offset", "utc"],
)
def test_nominal_duration_field_grounds_on_instants_not_wall_clock(tzinfo_flavour):
    """Grounding must not depend on which flavour of tzinfo the start datetime carries.

    Python subtracts two datetimes sharing one zoneinfo timezone on wall-clock time,
    so a calendar day across a transition would come out as 24 hours rather than 23.
    pytz sidesteps that by giving each instant its own fixed-offset tzinfo,
    which is why this only shows up once pandas hands back zoneinfo timezones.
    """
    naive = datetime(2023, 3, 26)
    if tzinfo_flavour == "pytz":
        start = pytz.timezone("Europe/Amsterdam").localize(naive)
    elif tzinfo_flavour == "zoneinfo":
        start = naive.replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    elif tzinfo_flavour == "fixed-offset":
        start = isodate.parse_datetime("2023-03-26T00:00:00+01:00")
    else:
        start = isodate.parse_datetime("2023-03-25T23:00:00+00:00")

    deser = NominalDurationField().deserialize("P1D", None, None)
    grounded = DurationField.ground_from(deser, start, timezone="Europe/Amsterdam")
    assert grounded == timedelta(hours=23)


def test_ground_from_falls_back_on_an_unknown_timezone():
    """An unknown timezone is not fatal, whether pandas is backed by pytz or by zoneinfo.

    The two raise different exceptions, so both have to be caught.
    """
    deser = NominalDurationField().deserialize("P1D", None, None)
    start = isodate.parse_datetime("2023-03-26T00:00:00+01:00")
    assert DurationField.ground_from(deser, start, timezone="Not/AZone") == timedelta(
        hours=24
    )


@pytest.mark.parametrize(
    "duration_input, exp_needs_calendar",
    [
        ("P1Y", True),
        ("P1M", True),
        ("P1Y2M", True),
        ("P1W", False),
        ("P1D", False),
        ("PT24H", False),
        ("P1DT1H", False),
    ],
)
def test_needs_a_calendar(duration_input, exp_needs_calendar):
    """Only years and months have no length at all until placed on a calendar."""
    deser = NominalDurationField().deserialize(duration_input, None, None)
    assert needs_a_calendar(deser) is exp_needs_calendar
    # the same verdict is reached for what a plain DurationField reports.
    assert (
        needs_a_calendar(DurationField().deserialize(duration_input, None, None))
        is exp_needs_calendar
    )
