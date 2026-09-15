import pytest
from marshmallow import ValidationError

from flexmeasures.data.schemas.automations import (
    AutomationCreationSchema,
    CronField,
    TimezoneField,
)


def test_cron_field_accepts_five_field_expression():
    assert CronField().deserialize("0 6 * * *") == "0 6 * * *"


@pytest.mark.parametrize(
    "cronstr",
    (
        "*/10 * * * * *",
        "0 */10 * * * * 2026",
        "@daily",
    ),
)
def test_cron_field_rejects_non_five_field_expression(cronstr):
    with pytest.raises(ValidationError, match="exactly five fields"):
        CronField().deserialize(cronstr)


@pytest.mark.parametrize("timezone", ("UTC", "Europe/Amsterdam", "Etc/GMT+1"))
def test_timezone_field_accepts_iana_names(timezone):
    assert TimezoneField().deserialize(timezone) == timezone


def test_timezone_field_rejects_unknown_name():
    with pytest.raises(ValidationError, match="does not exist"):
        TimezoneField().deserialize("Europe/NotAmsterdam")


@pytest.mark.parametrize(
    "payload, expected_timezone",
    [
        ({}, None),
        ({"timezone": None}, None),
        ({"timezone": "Europe/Amsterdam"}, "Europe/Amsterdam"),
    ],
)
def test_a_creation_leaves_the_timezone_to_the_asset_unless_it_names_one(
    payload, expected_timezone
):
    """Both omitting the timezone and sending an explicit null leave it to be resolved from the asset.

    `load_default=None` makes marshmallow treat the field as nullable, so neither form reaches validation,
    and `create_automation` is the one that decides what None means.
    """
    loaded = AutomationCreationSchema().load(
        {"name": "Day-ahead forecasts", "cronstr": "0 6 * * *", **payload}
    )

    assert loaded["timezone"] == expected_timezone


def test_a_creation_still_rejects_a_timezone_that_does_not_exist():
    with pytest.raises(ValidationError, match="does not exist"):
        AutomationCreationSchema().load(
            {
                "name": "Day-ahead forecasts",
                "cronstr": "0 6 * * *",
                "timezone": "Mars/Olympus",
            }
        )
