import pytest
from marshmallow import ValidationError

from flexmeasures.data.schemas.automations import CronField, TimezoneField


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
