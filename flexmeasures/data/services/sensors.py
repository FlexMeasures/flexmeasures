from __future__ import annotations

from werkzeug.exceptions import NotFound

from flexmeasures import Sensor, Account
from flexmeasures.data.models.generic_assets import GenericAsset


def get_sensors(
    account: Account | int | str | None = None,
    sensor_ids: list[int] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects.

    :param account: optionally, filter by account by passing an Account, int (account id) or string (account name).
    :param sensor_ids: optionally, filter by sensor id.
    """
    sensor_query = Sensor.query

    if account is not None:
        if isinstance(account, int):
            account = Account.query.filter_by(id=account_id).one_or_none()
            if not account:
                raise NotFound(f"There is no account with id {account_id}!")
        elif isinstance(account, str):
            account = Account.query.filter_by(name=account_name).one_or_none()
            if not account:
                raise NotFound(f"There is no account named {account_name}!")
        sensor_query = (
            sensor_query.join(GenericAsset)
            .filter(Sensor.generic_asset_id == GenericAsset.id)
            .filter(GenericAsset.owner == account)
        )
    if sensor_ids:
        sensor_query = sensor_query.filter(Sensor.id.in_(sensor_ids))

    return sensor_query.all()


def get_public_sensors(sensor_ids: list[int] | None = None) -> list[Sensor]:
    """Return a list of Sensor objects that belong to a public asset.

    :param sensor_ids: optionally, filter by sensor id.
    """
    sensor_query = (
        Sensor.query.join(GenericAsset)
        .filter(Sensor.generic_asset_id == GenericAsset.id)
        .filter(GenericAsset.account_id.is_(None))
    )
    if sensor_ids:
        sensor_query = sensor_query.filter(Sensor.id.in_(sensor_ids))
    return sensor_query.all()
