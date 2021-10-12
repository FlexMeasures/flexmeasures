from typing import Union

from flask import abort

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.user import User
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE


def check_user_access(user: User, sensor: Union[Sensor, Asset], permission: str):
    """
    Only allow access if the user is on the same account as the asset or if they are admins.

    Raises auth error if they are not.

    We look up the account of the owner to check. Editing public
    GenericAssets is thus only possible for admins.

    In the future, Assets will become Sensors, so then we'll drop that Asset check.
    For now: each Asset has a Generic Asset and a Sensor with matching ID. The GenericAsset.account_id
    should match that of asset.owner and should not change.
    """
    if user.has_role(ADMIN_ROLE):
        return
    if permission == "read" and user.has_role(ADMIN_READER_ROLE):
        return
    access_valid = False
    if isinstance(sensor, Asset):
        if user and user.account == sensor.owner.account:
            access_valid = True
    else:
        if user and user.account == sensor.generic_asset.owner:
            access_valid = True

    if not access_valid:
        raise abort(
            403,
            f"User {user.username} is not allowed to access Asset {sensor.name}, as their account differs.",
        )
