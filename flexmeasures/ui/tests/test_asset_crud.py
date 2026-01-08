from flask import url_for

import pytest
import json
import copy

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import (
    mock_asset_data,
    mock_asset_data_with_kpis,
    mock_asset_data_as_form_input,
)

"""
Testing if our asset UI proceeds with the expected round trip.
Here, we mock the API responses (we have to, as our UI layer contacts FlexMeasures as a server, which does not run during tests).
The real logic tests are done in the api package, which is also the better place for that.
"""

api_path_assets = "http://localhost//api/v3_0/assets"


def test_assets_page_empty(db, client, as_prosumer_user1):
    asset_index = client.get(url_for("AssetCrudUI:index"), follow_redirects=True)
    assert asset_index.status_code == 200


def test_new_asset_page(client, setup_assets, as_admin):
    asset_page = client.get(url_for("AssetCrudUI:get", id="new"), follow_redirects=True)
    assert asset_page.status_code == 200
    assert b"Creating a new asset" in asset_page.data


@pytest.mark.parametrize(
    "view",
    [
        "get",  # tests redirect to context
        "context",
        "graphs",
        "properties",
        "auditlog",
    ],
)
def test_asset_page(db, client, setup_assets, as_prosumer_user1, view):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)

    asset_page = client.get(
        url_for(
            f"AssetCrudUI:{view}",
            id=asset.id,
            start_time="2022-10-01T00:00:00+02:00",
            end_time="2022-10-02T00:00:00+02:00",
        ),
        follow_redirects=True,
    )
    assert asset_page.status_code == 200
    if view in ("get", "context"):
        assert "Show sensors".encode() in asset_page.data
        assert "Edit flex-context".encode() in asset_page.data
        assert "Structure".encode() in asset_page.data
        assert "Location".encode() in asset_page.data


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
    db, client, setup_assets, as_prosumer_user1, args, error
):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    asset = user.account.generic_assets[0]
    db.session.expunge(user)

    asset_page = client.get(
        url_for(
            "AssetCrudUI:graphs",
            id=asset.id,
            **args,
        ),
        follow_redirects=True,
    )
    assert error.encode() in asset_page.data
    assert "UNPROCESSABLE_ENTITY".encode() in asset_page.data


def test_add_asset(db, client, setup_assets, as_admin):
    """Add a new asset"""
    user = find_user_by_email("test_prosumer_user@seita.nl")
    mock_asset = mock_asset_data(account_id=user.account.id, as_list=False)

    response = client.post(
        url_for("AssetCrudUI:post", id="create"),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200  # response is HTML form
    assert "html" in response.content_type
    assert b"Creation was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_edit_asset(db, client, setup_assets, as_admin):
    mock_asset = mock_asset_data_with_kpis(db=db, as_list=False)
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(mock_asset),
    )
    assert response.status_code == 200
    assert b"Editing was successful" in response.data
    assert mock_asset["name"] in str(response.data)
    assert str(mock_asset["latitude"]) in str(response.data)
    assert str(mock_asset["longitude"]) in str(response.data)


def test_sensors_to_show_as_kpis_json(db, client, setup_assets, as_admin):
    mock_asset = mock_asset_data_with_kpis(db=db, as_list=False)

    # Test asset with invalid json
    ma_copy = copy.deepcopy(mock_asset)
    ma_copy["sensors_to_show_as_kpis"] = "not a json."
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(ma_copy),
    )
    # how the UI works is that the page reloads with 200 but there is a an error message string that checks if the editing was successful or not
    assert response.status_code == 200
    assert b"Cannot edit asset:" in response.data
    assert b"Invalid JSON" in response.data

    # Test invalid function in the sensors_to_show_as_kpis
    ma_copy = copy.deepcopy(mock_asset)
    ma_copy["sensors_to_show_as_kpis"] = json.loads(ma_copy["sensors_to_show_as_kpis"])
    ma_copy["sensors_to_show_as_kpis"][0]["function"] = "not valid function"
    # Stringify the sensors_to_show_as_kpis
    ma_copy["sensors_to_show_as_kpis"] = json.dumps(ma_copy["sensors_to_show_as_kpis"])
    response = client.post(
        url_for("AssetCrudUI:post", id=1),
        follow_redirects=True,
        data=mock_asset_data_as_form_input(ma_copy),
    )
    assert response.status_code == 200
    assert b"Cannot edit asset:" in response.data
    assert b"Must be one of: sum, min, max, mean." in response.data


def test_delete_asset(client, db, as_admin):
    """Delete an asset"""
    response = client.get(
        url_for("AssetCrudUI:delete_with_data", id=1),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"have been deleted" in response.data
