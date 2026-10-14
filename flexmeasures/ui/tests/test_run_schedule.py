"""Permission boundaries of the manual scheduling wizard."""

from unittest.mock import patch

import pytest
from flask import url_for
from flexmeasures.data.models.generic_assets import GenericAsset

PERIOD = {
    "start_time": "2026-10-14T12:00:00+00:00",
    "end_time": "2026-10-15T12:00:00+00:00",
}


@pytest.fixture(scope="module")
def public_asset(db, setup_generic_asset_types):
    asset = GenericAsset(
        name="schedule-public-asset",
        generic_asset_type=setup_generic_asset_types["battery"],
    )
    db.session.add(asset)
    db.session.commit()
    return asset


def test_graph_does_not_lookup_sensors(client, public_asset, as_admin):
    with patch("flexmeasures.ui.views.assets.scheduling.schedule_options") as lookup:
        response = client.get(url_for("AssetCrudUI:graphs", id=public_asset.id))
    assert response.status_code == 200
    assert b'id="runScheduleModal"' in response.data
    lookup.assert_not_called()


def test_reader_cannot_open_wizard(client, public_asset, as_prosumer_user1):
    with patch("flexmeasures.ui.views.assets.scheduling.schedule_options") as lookup:
        response = client.get(
            url_for("AssetCrudUI:schedule_options", id=public_asset.id),
            query_string=PERIOD,
        )
    assert response.status_code == 403
    lookup.assert_not_called()
    page = client.get(url_for("AssetCrudUI:graphs", id=public_asset.id))
    assert page.status_code == 200
    assert b'id="runScheduleModal"' not in page.data


def test_reader_cannot_save_defaults(client, public_asset, as_prosumer_user1):
    with patch(
        "flexmeasures.ui.views.assets.scheduling.save_schedule_defaults"
    ) as save:
        response = client.post(
            url_for("AssetCrudUI:schedule_defaults", id=public_asset.id),
            json={"power_capacity": "5 kW"},
        )
    assert response.status_code == 403
    save.assert_not_called()
    assert "power-capacity" not in public_asset.flex_model


@pytest.mark.parametrize("endpoint", ["schedule_options", "schedule_defaults"])
def test_wizard_requires_login(client, public_asset, endpoint):
    url = url_for(f"AssetCrudUI:{endpoint}", id=public_asset.id)
    response = (
        client.get(url, query_string=PERIOD)
        if endpoint == "schedule_options"
        else client.post(url, json={"power_capacity": "5 kW"})
    )
    assert response.status_code in (302, 401)
