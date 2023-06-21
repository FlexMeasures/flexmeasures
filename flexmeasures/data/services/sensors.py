from __future__ import annotations

from functools import lru_cache

import sqlalchemy as sa

from flexmeasures import Sensor, Account
from flexmeasures.data.models.generic_assets import GenericAsset


def get_sensors(
    account: Account | list[Account] | None,
    include_public_assets: bool = False,
    sensor_id_allowlist: list[int] | None = None,
    sensor_name_allowlist: list[str] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects that belong to the given account, and/or public sensors.

    :param account:                 select only sensors from this account (or list of accounts)
    :param include_public_assets:   if True, include sensors that belong to a public asset
    :param sensor_id_allowlist:     optionally, allow only sensors whose id is in this list
    :param sensor_name_allowlist:   optionally, allow only sensors whose name is in this list
    """
    # Just convert arguments to hashable types; the real implementation has been moved to _get_sensors (which is cached)
    if account is None:
        account_ids = tuple()
    elif isinstance(account, list):
        account_ids = tuple(account.id for account in account)
    else:
        account_ids = tuple([account.id])
    if sensor_id_allowlist is not None:
        sensor_id_allowlist = tuple(sensor_id_allowlist)
    if sensor_name_allowlist is not None:
        sensor_name_allowlist = tuple(sensor_name_allowlist)
    return _get_sensors(
        account_ids=account_ids,
        include_public_assets=include_public_assets,
        sensor_id_allowlist=sensor_id_allowlist,
        sensor_name_allowlist=sensor_name_allowlist,
    )


@lru_cache
def _get_sensors(
    account_ids: tuple[int],
    include_public_assets: bool = False,
    sensor_id_allowlist: tuple[int] | None = None,
    sensor_name_allowlist: tuple[str] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects that belong to the given account, and/or public sensors.

    :param account_ids:             select only sensors from assets with these account ids
    :param include_public_assets:   if True, include sensors that belong to a public asset
    :param sensor_id_allowlist:     optionally, allow only sensors whose id is in this list
    :param sensor_name_allowlist:   optionally, allow only sensors whose name is in this list
    """
    sensor_query = Sensor.query
    sensor_query = sensor_query.join(GenericAsset).filter(
        Sensor.generic_asset_id == GenericAsset.id
    )
    if include_public_assets:
        sensor_query = sensor_query.filter(
            sa.or_(
                GenericAsset.account_id.in_(account_ids),
                GenericAsset.account_id.is_(None),
            )
        )
    else:
        sensor_query = sensor_query.filter(GenericAsset.account_id.in_(account_ids))
    if sensor_id_allowlist:
        sensor_query = sensor_query.filter(Sensor.id.in_(sensor_id_allowlist))
    if sensor_name_allowlist:
        sensor_query = sensor_query.filter(Sensor.name.in_(sensor_name_allowlist))
    return sensor_query.all()
