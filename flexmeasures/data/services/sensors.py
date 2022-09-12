from __future__ import annotations

import sqlalchemy as sa

from flexmeasures import Sensor, Account
from flexmeasures.data.models.generic_assets import GenericAsset


def get_account_sensors(
    accounts: list[Account | None],
    sensor_ids: list[int] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects that belong to any of the given accounts.

    :param accounts: select only sensors from this list of accounts
                     (include None to select sensors that belong to a public asset).
    :param sensor_ids: optionally, filter by sensor id.
    """
    account_ids = [account.id for account in accounts if account is not None]
    sensor_query = Sensor.query.join(GenericAsset).filter(
        Sensor.generic_asset_id == GenericAsset.id
    )
    if None in accounts:
        sensor_query = sensor_query.filter(
            sa.or_(
                GenericAsset.account_id.in_(account_ids),
                GenericAsset.account_id.is_(None),
            )
        )
    else:
        sensor_query = sensor_query.filter(GenericAsset.account_id.in_(account_ids))
    if sensor_ids:
        sensor_query = sensor_query.filter(Sensor.id.in_(sensor_ids))
    return sensor_query.all()
