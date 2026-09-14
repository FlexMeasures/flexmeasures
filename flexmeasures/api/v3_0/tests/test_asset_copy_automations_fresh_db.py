"""Copying an asset subtree also copies its automations (see issue #2528)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from sqlalchemy import func, select

from flexmeasures import Forecaster
from flexmeasures.api.common.utils.api_utils import copy_asset
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.data_sources import get_data_generator

OLD_CURSOR = datetime(2020, 1, 1, 6, 0, tzinfo=timezone.utc)


def _add_sensor(db, asset: GenericAsset, name: str) -> Sensor:
    """Add a 15-minute power sensor to an asset."""
    sensor = Sensor(
        name=name,
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(sensor)
    db.session.flush()
    return sensor


def _add_automation(
    db,
    asset: GenericAsset,
    name: str,
    parameters: dict,
    config: dict | None = None,
    generator: DataSource | None = None,
) -> Automation:
    """Add an active forecast automation with a past cursor, so that a copy's fresh cursor stands out."""
    if generator is None:
        forecaster = get_data_generator(
            source=None,
            model="TrainPredictPipeline",
            config=config or {},
            save_config=True,
            data_generator_type=Forecaster,
        )
        assert forecaster is not None
        generator = forecaster.data_source
    db.session.flush()
    automation = Automation(
        asset=asset,
        generator=generator,
        type="forecasts",
        name=name,
        cronstr="0 6 * * *",
        timezone="Europe/Amsterdam",
        active=True,
        cursor=OLD_CURSOR,
        parameters=parameters,
    )
    db.session.add(automation)
    db.session.flush()
    return automation


@pytest.fixture()
def automated_site(fresh_db, setup_generic_assets_fresh_db):
    """A two-level asset subtree whose automations reference sensors across it.

    Layout:

    Site (Prosumer)
    ├── power sensor, forecast by the site automation with the meter's temperature as a regressor
    └── Meter (child)
          └── temperature sensor, forecast by the meter automation

    A second Prosumer asset sits outside the subtree, to reference from tests about external sensors.
    """
    site = setup_generic_assets_fresh_db["test_battery"]
    meter = GenericAsset(
        name="Test meter",
        generic_asset_type=site.generic_asset_type,
        owner=site.owner,
        parent_asset=site,
    )
    neighbour = GenericAsset(
        name="Test neighbouring site",
        generic_asset_type=site.generic_asset_type,
        owner=site.owner,
    )
    fresh_db.session.add_all([meter, neighbour])
    fresh_db.session.flush()

    power = _add_sensor(fresh_db, site, "site power")
    temperature = _add_sensor(fresh_db, meter, "meter temperature")
    neighbouring_power = _add_sensor(fresh_db, neighbour, "neighbouring power")

    site_automation = _add_automation(
        fresh_db,
        asset=site,
        name="Site power forecasts",
        parameters={"sensor": power.id, "sensor-to-save": power.id},
        config={"regressors": [temperature.id]},
    )
    meter_automation = _add_automation(
        fresh_db,
        asset=meter,
        name="Meter temperature forecasts",
        parameters={"sensor": temperature.id},
    )
    fresh_db.session.commit()
    return dict(
        site=site,
        meter=meter,
        neighbour=neighbour,
        power=power,
        temperature=temperature,
        neighbouring_power=neighbouring_power,
        site_automation=site_automation,
        meter_automation=meter_automation,
    )


def _automations_of(db, asset: GenericAsset) -> list[Automation]:
    """The automations of one asset, oldest first."""
    return (
        db.session.scalars(
            select(Automation)
            .filter(Automation.asset_id == asset.id)
            .order_by(Automation.id)
        )
        .unique()
        .all()
    )


def _child_of(db, asset: GenericAsset) -> GenericAsset:
    """The single child asset of an asset."""
    return db.session.scalars(
        select(GenericAsset).filter(GenericAsset.parent_asset_id == asset.id)
    ).one()


def _sensor_named(db, asset: GenericAsset, name: str) -> Sensor:
    """The sensor of an asset with the given name."""
    return db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id == asset.id, Sensor.name == name)
    ).one()


def test_copy_copies_direct_and_descendant_automations(fresh_db, automated_site):
    """Automations on the copied asset and on its descendants are copied, inactive and without run history."""
    asset_copy = copy_asset(automated_site["site"])

    assert asset_copy.skipped_automations == []
    site_copy = asset_copy.asset
    meter_copy = _child_of(fresh_db, site_copy)

    copied_site_automations = _automations_of(fresh_db, site_copy)
    copied_meter_automations = _automations_of(fresh_db, meter_copy)
    assert [automation.name for automation in copied_site_automations] == [
        "Site power forecasts"
    ]
    assert [automation.name for automation in copied_meter_automations] == [
        "Meter temperature forecasts"
    ]

    for copied, original in (
        (copied_site_automations[0], automated_site["site_automation"]),
        (copied_meter_automations[0], automated_site["meter_automation"]),
    ):
        assert copied.id != original.id
        assert copied.type == original.type
        assert copied.cronstr == original.cronstr
        assert copied.timezone == original.timezone
        # A copy waits to be switched on, and starts without the original's run history.
        assert copied.active is False
        assert copied.cursor > OLD_CURSOR

        # The original is left untouched.
        assert original.active is True
        assert original.cursor == OLD_CURSOR


def test_copied_automations_point_at_the_copied_sensors(fresh_db, automated_site):
    """Sensor references in parameters and in generator configuration follow the copy, across assets."""
    original_generator = automated_site["site_automation"].generator
    original_config = dict(original_generator.attributes["data_generator"]["config"])

    asset_copy = copy_asset(automated_site["site"])
    site_copy = asset_copy.asset
    meter_copy = _child_of(fresh_db, site_copy)
    power_copy = _sensor_named(fresh_db, site_copy, "site power")
    temperature_copy = _sensor_named(fresh_db, meter_copy, "meter temperature")

    copied_site_automation = _automations_of(fresh_db, site_copy)[0]
    copied_meter_automation = _automations_of(fresh_db, meter_copy)[0]

    # Parameters point at the copied sensors, not at the originals.
    assert copied_site_automation.parameters["sensor"] == power_copy.id
    assert copied_site_automation.parameters["sensor-to-save"] == power_copy.id
    assert copied_meter_automation.parameters["sensor"] == temperature_copy.id

    # The regressor on the other asset in the subtree follows the copy too.
    copied_config = copied_site_automation.generator.attributes["data_generator"][
        "config"
    ]
    assert copied_config["future-regressors"] == [temperature_copy.id]
    assert copied_config["past-regressors"] == [temperature_copy.id]

    # The copy got its own generator, so editing it cannot change the original's.
    assert (
        copied_site_automation.generator_id
        != automated_site["site_automation"].generator_id
    )
    assert original_generator.attributes["data_generator"]["config"] == original_config
    assert automated_site["site_automation"].parameters["sensor"] == (
        automated_site["power"].id
    )


def test_copied_automation_keeps_a_public_regressor(
    fresh_db, setup_generic_assets_fresh_db, automated_site
):
    """A regressor on a public asset stays shared, as every organisation may read it."""
    public_sensor = _add_sensor(
        fresh_db, setup_generic_assets_fresh_db["troposphere"], "public irradiance"
    )
    automation = _add_automation(
        fresh_db,
        asset=automated_site["meter"],
        name="Meter forecasts with public regressor",
        parameters={"sensor": automated_site["temperature"].id},
        config={"regressors": [public_sensor.id]},
    )
    fresh_db.session.commit()

    asset_copy = copy_asset(automated_site["site"])

    assert asset_copy.skipped_automations == []
    meter_copy = _child_of(fresh_db, asset_copy.asset)
    copied = [
        copied_automation
        for copied_automation in _automations_of(fresh_db, meter_copy)
        if copied_automation.name == automation.name
    ][0]
    copied_config = copied.generator.attributes["data_generator"]["config"]
    assert copied_config["future-regressors"] == [public_sensor.id]
    # An unchanged configuration is shared, rather than duplicated.
    assert copied.generator_id == automation.generator_id


def test_copy_within_the_same_organisation_keeps_an_external_regressor(
    fresh_db, automated_site
):
    """A regressor elsewhere in the same organisation stays usable, because the copy may still read it."""
    elsewhere = automated_site["neighbouring_power"]
    automation = _add_automation(
        fresh_db,
        asset=automated_site["site"],
        name="Site forecasts with neighbouring regressor",
        parameters={"sensor": automated_site["power"].id},
        config={"regressors": [elsewhere.id]},
    )
    fresh_db.session.commit()

    asset_copy = copy_asset(automated_site["site"])

    assert asset_copy.skipped_automations == []
    copied = [
        copied_automation
        for copied_automation in _automations_of(fresh_db, asset_copy.asset)
        if copied_automation.name == automation.name
    ][0]
    copied_config = copied.generator.attributes["data_generator"]["config"]
    assert copied_config["future-regressors"] == [elsewhere.id]


def test_cross_organisation_copy_skips_an_automation_reading_private_data(
    fresh_db, setup_accounts_fresh_db, automated_site
):
    """Copying to another organisation drops the automations that would read the first organisation's private data."""
    private_sensor = automated_site["neighbouring_power"]
    unsafe_automation = _add_automation(
        fresh_db,
        asset=automated_site["meter"],
        name="Meter forecasts with private regressor",
        parameters={"sensor": automated_site["temperature"].id},
        config={"regressors": [private_sensor.id]},
    )
    fresh_db.session.commit()
    data_sources_before = fresh_db.session.scalar(
        select(func.count()).select_from(DataSource)
    )

    asset_copy = copy_asset(
        automated_site["site"], account=setup_accounts_fresh_db["Supplier"]
    )

    # The asset, its sensors and the automations that are safe to copy all made it.
    site_copy = asset_copy.asset
    assert site_copy.account_id == setup_accounts_fresh_db["Supplier"].id
    meter_copy = _child_of(fresh_db, site_copy)
    assert _sensor_named(fresh_db, meter_copy, "meter temperature") is not None
    assert [automation.name for automation in _automations_of(fresh_db, site_copy)] == [
        "Site power forecasts"
    ]
    assert [
        automation.name for automation in _automations_of(fresh_db, meter_copy)
    ] == ["Meter temperature forecasts"]

    # The unsafe automation is reported, and left no records behind.
    assert len(asset_copy.skipped_automations) == 1
    skipped = asset_copy.skipped_automations[0]
    assert skipped.automation_id == unsafe_automation.id
    assert skipped.name == unsafe_automation.name
    assert skipped.asset_id == automated_site["meter"].id
    assert f"sensor {private_sensor.id}" in skipped.reason
    assert (
        fresh_db.session.scalar(
            select(func.count())
            .select_from(Automation)
            .filter(Automation.name == unsafe_automation.name)
        )
        == 1
    )
    # Only the copied site automation needed a generator of its own, so the skipped one left no data source behind.
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(DataSource))
        == data_sources_before + 1
    )

    # The original automation is untouched.
    assert unsafe_automation.active is True
    assert unsafe_automation.parameters["sensor"] == automated_site["temperature"].id


def test_copy_skips_an_automation_whose_generator_is_unavailable(
    fresh_db, automated_site
):
    """An automation whose data generator this instance does not know is skipped, not guessed at."""
    unknown_generator = DataSource(
        name="plugin forecaster",
        type="forecaster",
        model="ForecasterFromAPluginThatIsNotInstalled",
    )
    fresh_db.session.add(unknown_generator)
    fresh_db.session.flush()
    automation = _add_automation(
        fresh_db,
        asset=automated_site["site"],
        name="Forecasts from an unavailable generator",
        parameters={"sensor": automated_site["power"].id},
        generator=unknown_generator,
    )
    fresh_db.session.commit()

    asset_copy = copy_asset(automated_site["site"])

    assert [skipped.automation_id for skipped in asset_copy.skipped_automations] == [
        automation.id
    ]
    assert "data generator" in asset_copy.skipped_automations[0].reason
    assert [copied.name for copied in _automations_of(fresh_db, asset_copy.asset)] == [
        "Site power forecasts"
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_copy_asset_api_reports_skipped_automations(
    client,
    fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    automated_site,
    requesting_user,
):
    """The copy endpoint says which automations it left out, and why."""
    private_sensor = _add_sensor(
        fresh_db, setup_generic_assets_fresh_db["test_wind_turbine"], "supplier sensor"
    )
    unsafe_automation = _add_automation(
        fresh_db,
        asset=automated_site["site"],
        name="Site forecasts with supplier regressor",
        parameters={"sensor": automated_site["power"].id},
        config={"regressors": [private_sensor.id]},
    )
    fresh_db.session.commit()

    response = client.post(
        url_for("AssetAPI:copy_assets", id=automated_site["site"].id)
    )

    assert response.status_code == 201
    assert response.json["skipped_automations"] == [
        {
            "id": unsafe_automation.id,
            "name": unsafe_automation.name,
            "asset": automated_site["site"].id,
            "reason": (
                f"It references sensor {private_sensor.id}, which lies outside the copied assets"
                " and which the destination organisation cannot read."
            ),
        }
    ]
    assert "1 automation(s) could not be copied." in response.json["message"]

    copied_names = [
        automation.name
        for automation in _automations_of(
            fresh_db, fresh_db.session.get(GenericAsset, response.json["asset"])
        )
    ]
    assert copied_names == ["Site power forecasts"]
