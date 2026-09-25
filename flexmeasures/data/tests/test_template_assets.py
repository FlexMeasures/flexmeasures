import threading
import time

from sqlalchemy import func, select, text

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.scripts.data_gen import (
    populate_initial_structure,
    provision_default_template_assets,
    TEMPLATE_ASSETS_LOCK_KEY,
)


class _FailingDb:
    @property
    def session(self):
        raise AssertionError("Default data creation should not touch the database.")


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
    assert ev_charger.flex_model["soc-min"] == "0 kWh"
    assert ev_charger.flex_model["soc-minima"] == "12 kWh"

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


def test_initial_structure_creation_skips_database_commands(monkeypatch):
    monkeypatch.setattr("flexmeasures.data.is_running_database_command", lambda: True)

    populate_initial_structure(_FailingDb())


def test_template_asset_provisioning_skips_database_commands(fresh_db, monkeypatch):
    monkeypatch.setattr("flexmeasures.data.is_running_database_command", lambda: True)
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


def test_provisioning_waits_for_another_process_provisioning(fresh_db):
    """Provisioning waits for a concurrent one to commit, rather than inserting the same rows and failing.

    Another process is simulated by a thread with its own connection, which takes the provisioning lock,
    inserts the solar asset type, and only commits once our provisioning is waiting for it.
    With the lock, we wait on the lock; without it, our insert of that type waits on the unique index, and fails once the other one commits.
    Either way, our connection shows up in pg_stat_activity as waiting on a lock, which is what the other one waits for.
    It watches our connection only, so an unrelated backend waiting on a lock cannot set it off.
    """
    lock_taken = threading.Event()
    provisioning_waited = threading.Event()
    engine = fresh_db.engine  # needs the app context, which the thread does not have
    # The session keeps this connection for the transaction in which provisioning then runs.
    provisioning_pid = fresh_db.session.execute(
        text("SELECT pg_backend_pid()")
    ).scalar()

    def provision_in_another_process():
        with engine.connect() as connection, connection.begin():
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": TEMPLATE_ASSETS_LOCK_KEY},
            )
            connection.execute(
                text(
                    "INSERT INTO generic_asset_type (name, description) VALUES ('solar', 'solar panel(s)')"
                )
            )
            lock_taken.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                # Within a transaction, pg_stat_activity is a snapshot, unless we clear it.
                connection.execute(text("SELECT pg_stat_clear_snapshot()"))
                provisioning_waits = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = :pid AND wait_event_type = 'Lock'"
                    ),
                    {"pid": provisioning_pid},
                ).scalar()
                if provisioning_waits:
                    provisioning_waited.set()
                    return  # commit, now that the provisioning waits for us
                time.sleep(0.05)

    other_process = threading.Thread(target=provision_in_another_process)
    other_process.start()
    assert lock_taken.wait(timeout=10)
    try:
        provision_default_template_assets(fresh_db)
    finally:
        other_process.join()

    assert (
        provisioning_waited.is_set()
    ), "Provisioning never waited for the other process."
    assert (
        fresh_db.session.scalar(
            select(func.count())
            .select_from(GenericAssetType)
            .where(GenericAssetType.name == "solar")
        )
        == 1
    )
