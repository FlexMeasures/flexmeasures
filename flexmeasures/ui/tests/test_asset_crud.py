from flask import url_for

import pytest

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import mock_asset_response, mock_api_data_as_form_input
from flexmeasures.ui.crud.assets import get_assets_by_account

"""
Testing if our asset UI proceeds with the expected round trip.
Here, we mock the API responses (we have to, as our UI layer contacts FlexMeasures as a server, which does not run during tests).
The real logic tests are done in the api package, which is also the better place for that.
"""

api_path_assets = "http://localhost//api/v3_0/assets"


def test_assets_page_empty(db, client, requests_mock, as_prosumer_user1):
    requests_mock.get(f"{api_path_assets}", status_code=200, json=[])
    requests_mock.get(f"{api_path_assets}/public", status_code=200, json=[])
    asset_index = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert asset_index.status_code == 200


def test_get_assets_by_account(db, client, requests_mock, as_prosumer_user1):
    mock_assets = mock_asset_response(multiple=True)
    requests_mock.get(f"{api_path_assets}", status_code=200, json=mock_assets)
    assert get_assets_by_account(1)[1].name == "TestAsset2"


def test_new_asset_page(client, setup_assets, as_admin):
    asset_page = client.get(url_for("AssetCrudUI:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 200
    assert b"Creating a new asset" in asset_page.data


def test_asset_page(db, client, setup_assets, requests_mock, as_prosumer_user1):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)
    mock_asset = mock_asset_response(as_list=False)
    mock_asset["latitude"] = asset.latitude
    mock_asset["longitude"] = asset.longitude

    requests_mock.get(f"{api_path_assets}/{asset.id}", status_code=200, json=mock_asset)
    asset_page = client.get(
        url_for(
            "AssetCrudUI:get",
            id=asset.id,
            start_time="2022-10-01T00:00:00+02:00",
            end_time="2022-10-02T00:00:00+02:00",
        ),
        follow_redirects=True,
    )
    assert ("Edit %s" % mock_asset["name"]).encode() in asset_page.data
    assert str(mock_asset["latitude"]).encode() in asset_page.data
    assert str(mock_asset["longitude"]).encode() in asset_page.data
    print("asset_page.data:\n%s" % asset_page.data)
    assert (
        "storeStartDate = new Date('2022-10-01T00:00:00+02:00')".encode()
        in asset_page.data
    )
    assert (
        "storeEndDate = new Date('2022-10-02T00:00:00+02:00')".encode()
        in asset_page.data
    )


@pytest.mark.parametrize(
    "args, error",
    [
        (
            {"start_time": "2022-10-01T00:00:00+02:00"},
            "Both start_time and end_time must be provided together.",
        ),
        (
            {"end_time": "2022-10-01T00:00:00+02:00"},
            "Both start_time and end_time must be provided together.",
        ),
        (
            {
                "start_time": "2022-10-01T00:00:00+02:00",
                "end_time": "2022-10-01T00:00:00+02:00",
            },
            "start_time must be before end_time.",
        ),
        (
            {
                "start_time": "2022-10-01T00:00:00",
                "end_time": "2022-10-02T00:00:00+02:00",
            },
            "Not a valid aware datetime",
        ),
    ],
)
def test_asset_page_dates_validation(
    db, client, setup_assets, requests_mock, as_prosumer_user1, args, error
):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)
    mock_asset = mock_asset_response(as_list=False)

    requests_mock.get(f"{api_path_assets}/{asset.id}", status_code=200, json=mock_asset)
    asset_page = client.get(
        url_for(
            "AssetCrudUI:get",
            id=asset.id,
            **args,
        ),
        follow_redirects=True,
    )
    assert error.encode() in asset_page.data
    assert "UNPROCESSABLE_ENTITY".encode() in asset_page.data


def test_edit_asset(db, client, setup_assets, requests_mock, as_admin):
    mock_asset = mock_asset_response(as_list=False)
    requests_mock.patch(f"{api_path_assets}/1", status_code=200, json=mock_asset)
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_api_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200
    assert b"Editing was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_add_asset(db, client, setup_assets, requests_mock, as_admin):
    """Add a new asset"""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    mock_asset = mock_asset_response(account_id=user.account.id, as_list=False)
    del mock_asset[
        "generic_asset_type"
    ]  # API gives back more info here than a POST sends
    mock_asset["generic_asset_type_id"] = 1
    requests_mock.post(api_path_assets, status_code=201, json=mock_asset)
    response = client.post(
        url_for("AssetCrudUI:post", id="create"),
        follow_redirects=True,
        data=mock_api_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200  # response is HTML form
    assert "html" in response.content_type
    assert b"Creation was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_delete_asset(client, db, requests_mock, as_admin):
    """Delete an asset"""
    requests_mock.delete(f"{api_path_assets}/1", status_code=204, json={})
    requests_mock.get(api_path_assets, status_code=200, json={})
    requests_mock.get(f"{api_path_assets}/public", status_code=200, json={})
    response = client.get(
        url_for("AssetCrudUI:delete_with_data", id=1),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"have been deleted" in response.data
