from __future__ import annotations

from werkzeug.exceptions import NotFound

from flexmeasures import Sensor, Account
from flexmeasures.data.models.generic_assets import GenericAsset


def get_sensors(
    account_name: str | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects.

    :param account_name: optionally, filter by account name.
    """
    sensor_query = Sensor.query

    if account_name is not None:
        account = Account.query.filter(Account.name == account_name).one_or_none()
        if not account:
            raise NotFound(f"There is no account named {account_name}!")
        sensor_query = (
            sensor_query.join(GenericAsset)
            .filter(Sensor.generic_asset_id == GenericAsset.id)
            .filter(GenericAsset.owner == account)
        )

    return sensor_query.all()
