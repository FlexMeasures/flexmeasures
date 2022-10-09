from __future__ import annotations

import sqlalchemy as sa

from flexmeasures import Sensor, Account
from flexmeasures.data.models.generic_assets import GenericAsset


def get_sensors(
    accounts: list[Account | None] = None,
    filter_by_sensor_ids: list[int] | None = None,
    filter_by_sensor_names: list[str] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects that belong to any of the given accounts, and/or public sensors.

    :param accounts:                optionally, select only sensors from this list of accounts
                                    (include None to select sensors that belong to a public asset).
    :param filter_by_sensor_ids:    optionally, filter by sensor id.
    :param filter_by_sensor_names:  optionally, filter by sensor name.
    """
    sensor_query = Sensor.query
    if accounts is not None:
        account_ids = [account.id for account in accounts if account is not None]
        sensor_query = sensor_query.join(GenericAsset).filter(
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
    if filter_by_sensor_ids:
        sensor_query = sensor_query.filter(Sensor.id.in_(filter_by_sensor_ids))
    if filter_by_sensor_names:
        sensor_query = sensor_query.filter(Sensor.name.in_(filter_by_sensor_names))
    return sensor_query.all()
