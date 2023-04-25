from flask import url_for
import pytest

import pandas as pd

from flexmeasures.data.models.assets import Asset
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.api.tests.utils import check_deprecation, get_auth_token, UserContext
from flexmeasures.api.v2_0.tests.utils import get_asset_post_data


@pytest.mark.parametrize("use_owner_id, num_assets", [(False, 7), (True, 1)])
def test_get_assets(client, add_charging_station_assets, use_owner_id, num_assets):
    """
    Get assets, either for all users (our user here is admin, so is allowed to see all 7 assets) or for
    a unique one (prosumer user 2 has one asset ― "Test battery").
    """
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    test_prosumer2_id = find_user_by_email("test_prosumer_user_2@seita.nl").id

    query = {}
    if use_owner_id:
        query["owner_id"] = test_prosumer2_id

    get_assets_response = client.get(
        url_for("flexmeasures_api_v2_0.get_assets"),
        query_string=query,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_assets_response.json)
    check_deprecation(get_assets_response)
    assert get_assets_response.status_code == 200
    assert len(get_assets_response.json) == num_assets

    battery = {}
    for asset in get_assets_response.json:
        if asset["name"] == "Test battery":
            battery = asset
    assert battery
    assert pd.Timestamp(battery["soc_datetime"]) == pd.Timestamp(
        "2015-01-01T00:00:00+01:00"
    )
    assert battery["owner_id"] == test_prosumer2_id
    assert battery["capacity_in_mw"] == 2
