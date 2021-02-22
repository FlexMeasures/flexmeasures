import copy

from flask import url_for


def login(the_client, email, password):
    auth_data = dict(email=email, password=password)
    login_response = the_client.post(
        url_for("security.login"), data=auth_data, follow_redirects=True
    )
    assert login_response.status_code == 200
    assert b"Please log in" not in login_response.data
    return login_response


def logout(client):
    return client.get(url_for("security.logout"), follow_redirects=True)


def mock_asset_response(
    asset_id: int = 1,
    owner_id: int = 3,
    market_id: int = 1,
    as_list: bool = True,
    multiple: bool = False,
) -> dict:
    asset = dict(
        id=asset_id,
        name="TestAsset",
        display_name="New Test Asset",
        asset_type_name="wind",
        market_id=int(market_id),
        owner_id=int(owner_id),
        capacity_in_mw=100,
        latitude=70.4,
        longitude=30.9,
        min_soc_in_mwh=0,
        max_soc_in_mwh=0,
        soc_in_mwh=0,
        event_resolution=22,  # "PT15M",
    )
    if as_list:
        asset_list = [asset]
        if multiple:
            asset2 = copy.deepcopy(asset)
            asset2["capacity_in_mw"] = 200
            asset_list.append(asset2)
        return asset_list
    return asset


def mock_user_response(
    user_id: int = 1,
    username: str = "Alex",
    email="alex@seita.nl",
    active: bool = True,
    as_list: bool = True,
    multiple: bool = False,
) -> dict:
    user = dict(
        id=user_id,
        username=username,
        email=email,
        active=active,
        password="secret",
        flexmeasures_roles=[1],
    )
    if as_list:
        user_list = [user]
        if multiple:
            user2 = copy.deepcopy(user)
            user2["id"] = 2
            user2["username"] = "Bert"
            user2["email"] = ("bert@seita.nl",)
            user_list.append(user2)
        return user_list
    return user


def mock_api_data_as_form_input(api_data: dict) -> dict:
    form_input = copy.deepcopy(api_data)
    form_input["owner"] = api_data["owner_id"]
    return form_input
