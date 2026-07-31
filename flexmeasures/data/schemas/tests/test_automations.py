import pytest
from marshmallow import ValidationError

from flexmeasures.data.schemas.automations import CronField


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
