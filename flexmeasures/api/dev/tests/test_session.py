"""The endpoints that store a user's choices in the FlexMeasures UI in their session."""

import pytest
from flask import url_for


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("tab", ["jobs", "sensors"])
def test_update_status_page_tab(client, setup_api_test_data, requesting_user, tab):
    """Posting a status page tab records it in the session, for the next status page the user opens."""
    response = client.post(
        url_for("SessionAPI:update_status_page_tab"),
        json={"status-page-tab": tab},
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["status_page_tab"] == tab


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_update_status_page_tab_rejects_unknown_tab(
    client, setup_api_test_data, requesting_user
):
    """Only the two tabs the status page actually has are accepted."""
    response = client.post(
        url_for("SessionAPI:update_status_page_tab"),
        json={"status-page-tab": "automations"},
    )
    assert response.status_code == 422
    with client.session_transaction() as session:
        assert "status_page_tab" not in session


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "endpoint, session_key",
    [
        ("update_status_page_child_jobs", "status_page_include_child_assets"),
        (
            "update_automations_page_child_assets",
            "automations_page_include_child_assets",
        ),
    ],
)
@pytest.mark.parametrize(
    "body, expected",
    [
        ({"include-child-assets": True}, True),
        ({"include-child-assets": False}, False),
        # Listing the assets below as well asks more of the server, so a page only does so when asked to.
        ({}, False),
    ],
)
def test_update_page_scope(
    client, setup_api_test_data, requesting_user, endpoint, session_key, body, expected
):
    """Posting whether a page lists the assets below the asset, too, records it in the session for the next visit."""
    response = client.post(url_for(f"SessionAPI:{endpoint}"), json=body)
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session[session_key] is expected


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_update_default_asset_view(client, setup_api_test_data, requesting_user):
    """A default asset view is recorded, and cleared again when it is no longer to be used as default."""
    response = client.post(
        url_for("SessionAPI:update_default_asset_view"),
        json={"default-asset-view": "Graphs"},
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["default_asset_view"] == "Graphs"

    response = client.post(
        url_for("SessionAPI:update_default_asset_view"),
        json={"use-as-default": False},
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "default_asset_view" not in session


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_update_keep_legends_below_graphs(client, setup_api_test_data, requesting_user):
    """Keeping legends below graphs is recorded, and cleared again when switched off."""
    response = client.post(
        url_for("SessionAPI:update_keep_legends_below_graphs"),
        json={"keep-legends-below-graphs": True},
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["keep_legends_below_graphs"] is True

    response = client.post(
        url_for("SessionAPI:update_keep_legends_below_graphs"),
        json={"keep-legends-below-graphs": False},
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "keep_legends_below_graphs" not in session


def test_session_endpoints_need_a_logged_in_user(client, setup_api_test_data):
    response = client.post(
        url_for("SessionAPI:update_status_page_tab"),
        json={"status-page-tab": "jobs"},
    )
    assert response.status_code == 401
