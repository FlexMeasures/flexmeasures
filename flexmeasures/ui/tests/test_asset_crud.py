from flask import url_for

import pytest

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import mock_asset_response, mock_api_data_as_form_input

"""
Testing if our asset UI proceeds with the expected roundtrip.
Here, we mock the API responses (we have to, as our UI layer contacts FlexMeasures as a server, which does not run during tests).
The real logic tests are done in the api package, which is also the better place for that.
"""


def test_assets_page_empty(db, client, requests_mock, as_prosumer):
    requests_mock.get("http://localhost//api/v2_0/assets", status_code=200, json={})
    asset_index = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert asset_index.status_code == 200


@pytest.mark.parametrize("use_owned_by", [False, True])
def test_assets_page_nonempty(db, client, requests_mock, as_prosumer, use_owned_by):
    mock_assets = mock_asset_response(multiple=True)
    requests_mock.get(
        "http://localhost//api/v2_0/assets", status_code=200, json=mock_assets
    )
    if use_owned_by:
        asset_index = client.get(
            url_for("AssetCrudUI:owned_by", owner_id=mock_assets[0]["owner_id"])
        )
    else:
        asset_index = client.get(url_for("AssetCrudUI:index"))
    for asset in mock_assets:
        assert asset["display_name"].encode() in asset_index.data


def test_new_asset_page(client, as_admin):
    asset_page = client.get(url_for("AssetCrudUI:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 200
    assert b"Creating a new asset" in asset_page.data


def test_asset_page(db, client, requests_mock, as_prosumer):
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    asset = prosumer.assets[0]
    db.session.expunge(prosumer)
    mock_asset = mock_asset_response(as_list=False)
    mock_asset["capacity_in_mw"] = asset.capacity_in_mw
    mock_asset["latitude"] = asset.latitude
    mock_asset["longitude"] = asset.longitude

    requests_mock.get(
        f"http://localhost//api/v2_0/asset/{asset.id}", status_code=200, json=mock_asset
    )
    asset_page = client.get(
        url_for("AssetCrudUI:get", id=asset.id), follow_redirects=True
    )
    assert ("Edit asset %s" % mock_asset["display_name"]).encode() in asset_page.data
    assert str(mock_asset["capacity_in_mw"]).encode() in asset_page.data
    assert str(mock_asset["latitude"]).encode() in asset_page.data
    assert str(mock_asset["longitude"]).encode() in asset_page.data


def test_edit_asset(db, client, requests_mock, as_admin):
    mock_asset = mock_asset_response(as_list=False)
    requests_mock.patch(
        "http://localhost//api/v2_0/asset/1", status_code=200, json=mock_asset
    )
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_api_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200
    assert b"Editing was successful" in response.data
    assert mock_asset["display_name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_add_asset(db, client, requests_mock, as_admin):
    """Add a new asset"""
    prosumer = find_user_by_email("test_prosumer@seita.nl")
    mock_asset = mock_asset_response(owner_id=prosumer.id, as_list=False)
    requests_mock.post(
        "http://localhost//api/v2_0/assets", status_code=201, json=mock_asset
    )
    response = client.post(
        url_for("AssetCrudUI:post", id="create"),
        follow_redirects=True,
        data=mock_api_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200  # response is HTML form
    assert "html" in response.content_type
    assert b"Creation was successful" in response.data
    assert mock_asset["display_name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_delete_asset(client, db, requests_mock, as_admin):
    """Delete an asset"""
    requests_mock.delete("http://localhost//api/v2_0/asset/1", status_code=204, json={})
    requests_mock.get("http://localhost//api/v2_0/assets", status_code=200, json={})
    response = client.get(
        url_for("AssetCrudUI:delete_with_data", id=1),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"have been deleted" in response.data
