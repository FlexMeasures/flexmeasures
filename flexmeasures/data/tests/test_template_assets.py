from sqlalchemy import func, select

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.scripts.data_gen import provision_default_template_assets


def test_provision_default_template_assets_creates_single_asset_templates(
    fresh_db, app
):
    provision_default_template_assets(fresh_db)

    assets = fresh_db.session.scalars(
        select(GenericAsset).where(GenericAsset.account_id.is_(None))
    ).all()
    assets_by_name = {asset.name: asset for asset in assets}

    assert set(assets_by_name) >= {
        "Battery Template",
        "EV Charger Template",
        "Heat Pump Template",
    }

    battery = assets_by_name["Battery Template"]
    assert battery.generic_asset_type.name == "battery"
    assert battery.attributes["template"]["key"] == "battery-template"
    assert battery.attributes["template"]["has_scenarios"] is False
    assert battery.description.startswith("Single battery asset")

    ev_charger = assets_by_name["EV Charger Template"]
    assert ev_charger.generic_asset_type.name == "one-way_evse"
    assert ev_charger.attributes["template"]["key"] == "ev-charger-template"
    assert ev_charger.description.startswith("Single EV charger asset")

    heat_pump = assets_by_name["Heat Pump Template"]
    assert heat_pump.generic_asset_type.name == "heat-storage"
    assert heat_pump.attributes["template"]["key"] == "heat-pump-template"
    assert heat_pump.description.startswith("Single heat-pump-with-buffer style asset")

    battery_sensor_names = {sensor.name for sensor in battery.sensors}
    ev_sensor_names = {sensor.name for sensor in ev_charger.sensors}
    heat_sensor_names = {sensor.name for sensor in heat_pump.sensors}

    assert battery_sensor_names == {"electricity-power", "state-of-charge"}
    assert ev_sensor_names == {"electricity-power", "state-of-charge"}
    assert heat_sensor_names == {"electricity-power", "state-of-charge"}

    battery_soc_sensor = next(
        sensor for sensor in battery.sensors if sensor.name == "state-of-charge"
    )
    assert battery.flex_model["state-of-charge"]["sensor"] == battery_soc_sensor.id

    assert app.config["FLEXMEASURES_CREATE_TEMPLATE_ASSETS_ON_STARTUP"] is False


def test_provision_default_template_assets_is_idempotent(fresh_db):
    provision_default_template_assets(fresh_db)
    asset_count = fresh_db.session.scalar(
        select(func.count()).select_from(GenericAsset)
    )
    sensor_count = fresh_db.session.scalar(select(func.count()).select_from(Sensor))

    provision_default_template_assets(fresh_db)
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(GenericAsset))
        == asset_count
    )
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(Sensor))
        == sensor_count
    )
