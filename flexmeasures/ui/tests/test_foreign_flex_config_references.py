"""An asset's charts and status page show nothing of another account's assets and sensors that its flex config refers to."""

import json
import re
from datetime import timedelta

import pytest
from flask import url_for
from flask_login import login_user, logout_user

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.users import find_user_by_email


@pytest.fixture
def own_and_foreign(db, setup_accounts, setup_generic_asset_types):
    battery = setup_generic_asset_types["battery"]
    foreign_asset = GenericAsset(
        name="foreign flex asset",
        generic_asset_type=battery,
        owner=setup_accounts["Supplier"],
        flex_model={"soc-min": "123 kWh"},
    )
    foreign_sensor = Sensor(
        name="foreign secret price",
        generic_asset=foreign_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    own_asset = GenericAsset(
        name="own flex asset",
        generic_asset_type=battery,
        owner=setup_accounts["Prosumer"],
        flex_model={"soc-max": "456 kWh"},
    )
    own_sensor = Sensor(
        name="own power",
        generic_asset=own_asset,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add_all([foreign_asset, foreign_sensor, own_asset, own_sensor])
    db.session.flush()
    # Stored directly, as references made before stored references were checked
    own_asset.flex_context = {"consumption-price": {"sensor": foreign_sensor.id}}
    own_asset.sensors_to_show = [
        {"title": "Power", "sensor": own_sensor.id},
        {
            "title": "Foreign",
            "plots": [{"asset": foreign_asset.id, "flex-model": "soc-min"}],
        },
        {"title": "Own", "plots": [{"asset": own_asset.id, "flex-model": "soc-max"}]},
    ]
    db.session.commit()
    yield own_asset, foreign_asset, foreign_sensor
    db.session.delete(own_sensor)
    db.session.delete(own_asset)
    db.session.delete(foreign_sensor)
    db.session.delete(foreign_asset)
    db.session.commit()


def test_status_page_leaves_out_unreadable_flex_context_sensors(
    client, own_and_foreign, as_prosumer_user1
):
    own_asset, _, foreign_sensor = own_and_foreign
    page = client.get(
        url_for("AssetCrudUI:status", id=own_asset.id), follow_redirects=True
    )
    assert page.status_code == 200
    listed = json.loads(
        re.search(r"const sensors = (\[.*?\]);", page.data.decode(), re.DOTALL).group(1)
    )
    assert foreign_sensor.id not in [sensor["id"] for sensor in listed]
    assert "foreign secret price" not in page.data.decode()


def test_sensors_to_show_leaves_out_flex_config_of_foreign_assets(app, own_and_foreign):
    own_asset, foreign_asset, _ = own_and_foreign
    user = find_user_by_email("test_prosumer_user@seita.nl")
    with app.test_request_context("/"):
        login_user(user)
        shown = own_asset.validate_sensors_to_show(suggest_default_sensors=False)
        logout_user()
    names = [
        sensor.name
        for entry in shown
        for plot in entry.get("plots", [])
        for sensor in plot.get("sensors", [])
    ]
    assert not [name for name in names if foreign_asset.name in name]
    assert any(own_asset.name in name for name in names)
