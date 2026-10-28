"""A report automation over one asset type of a group notes which members it aggregates, and which enter or leave that selection as their type changes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.services.automations import create_automation


def report_events_on(db, asset: GenericAsset) -> list[str]:
    return [
        event
        for event in db.session.scalars(
            select(AssetAuditLog.event)
            .filter_by(affected_asset_id=asset.id)
            .order_by(AssetAuditLog.id)
        )
        if "report automation" in event.lower()
    ]


@pytest.fixture
def street(fresh_db):
    """A street grouping a house and a heat pump, the house grouping two PV installations."""
    db = fresh_db
    site_type = GenericAssetType(name="site")
    solar = GenericAssetType(name="solar")
    heat = GenericAssetType(name="heat")
    db.session.add_all([site_type, solar, heat])
    street = GenericAsset(name="Street", generic_asset_type=site_type)
    db.session.add(street)
    db.session.flush()
    house = GenericAsset(
        name="House", generic_asset_type=site_type, parent_asset=street
    )
    db.session.add(house)
    db.session.flush()

    def power_sensor(name, asset, unit="kW"):
        sensor = Sensor(
            name,
            generic_asset=asset,
            unit=unit,
            event_resolution=timedelta(minutes=15),
        )
        db.session.add(sensor)
        return sensor

    street_pv = power_sensor("street PV", street, unit="MW")
    db.session.flush()
    street.flex_model = {"production": {"sensor": street_pv.id}}
    house.flex_model = {"group": {"asset": street.id}}

    devices = {}
    for name, asset_type, parent, group in (
        ("PV one", solar, house, house),
        ("PV two", solar, house, house),
        ("Heat pump", heat, street, street),
    ):
        device = GenericAsset(
            name=name, generic_asset_type=asset_type, parent_asset=parent
        )
        db.session.add(device)
        db.session.flush()
        sensor = power_sensor(f"{name} power", device)
        db.session.flush()
        device.flex_model = {
            "inflexible-production": {"sensor": sensor.id},
            "group": {"asset": group.id},
        }
        devices[name] = device
    db.session.commit()
    return dict(street=street, house=house, solar=solar, heat=heat, **devices)


def create_solar_report(street) -> int:
    automation, _ = create_automation(
        street["street"],
        name="Street PV",
        cronstr="0 1 * * *",
        automation_type="reporting",
        generator_class="AggregatorReporter",
        config={
            "group": {"asset": street["street"].id},
            "members": {"asset-type": "solar"},
        },
        parameters={"duration": "P1D", "end-offset": "DB"},
    )
    return automation.id


def test_a_filtered_report_notes_the_members_it_starts_with(fresh_db, street):
    automation_id = create_solar_report(street)
    fresh_db.session.commit()

    one, two = street["PV one"], street["PV two"]
    assert report_events_on(fresh_db, street["street"]) == [
        f"Report automation 'Street PV' ({automation_id}) aggregates the members of group asset 'Street' ({street['street'].id})"
        f" of asset type 'solar', starting with: 'PV one' ({one.id}), 'PV two' ({two.id})."
    ]


def test_a_member_whose_type_changes_into_the_filter_is_noted(fresh_db, street):
    automation_id = create_solar_report(street)
    fresh_db.session.commit()

    heat_pump = street["Heat pump"]
    heat_pump.generic_asset_type = street["solar"]
    fresh_db.session.commit()

    assert report_events_on(fresh_db, street["street"])[-1] == (
        f"Asset 'Heat pump' ({heat_pump.id}) entered the members of group asset 'Street' ({street['street'].id})"
        f" that report automation 'Street PV' ({automation_id}) aggregates,"
        f" filtered to asset type 'solar', as its type changed from 'heat' to 'solar'."
    )


def test_a_nested_member_whose_type_changes_out_of_the_filter_is_noted(
    fresh_db, street
):
    """PV one belongs to the street through the house, so its type change concerns the street's report."""
    create_solar_report(street)
    fresh_db.session.commit()

    pv = street["PV one"]
    pv.generic_asset_type_id = street["heat"].id
    fresh_db.session.commit()

    latest = report_events_on(fresh_db, street["street"])[-1]
    assert latest.startswith(f"Asset 'PV one' ({pv.id}) left the members of group")
    assert "changed from 'solar' to 'heat'" in latest


def test_a_type_change_outside_the_filter_notes_nothing(fresh_db, street):
    """Neither the old nor the new type is the one the report aggregates."""
    create_solar_report(street)
    fresh_db.session.commit()
    other = GenericAssetType(name="other")
    fresh_db.session.add(other)

    street["Heat pump"].generic_asset_type = other
    fresh_db.session.commit()

    assert len(report_events_on(fresh_db, street["street"])) == 1


def test_a_group_entry_changing_type_notes_nothing(fresh_db, street):
    """The filter applies to the devices behind a group, not to the group's own asset."""
    create_solar_report(street)
    fresh_db.session.commit()

    street["house"].generic_asset_type = street["solar"]
    fresh_db.session.commit()

    assert len(report_events_on(fresh_db, street["street"])) == 1


def test_a_device_joining_the_group_as_its_type_changes_is_not_noted_leaving(
    fresh_db, street
):
    """A solar device joins the street and becomes a heat device in one go, so it never was among the members the solar report aggregates."""
    create_solar_report(street)
    fresh_db.session.commit()
    loose = GenericAsset(
        name="Loose PV",
        generic_asset_type=street["solar"],
        parent_asset=street["street"],
    )
    fresh_db.session.add(loose)
    fresh_db.session.flush()
    sensor = Sensor(
        "Loose PV power",
        generic_asset=loose,
        unit="kW",
        event_resolution=timedelta(minutes=15),
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()
    loose.flex_model = {"inflexible-production": {"sensor": sensor.id}}
    fresh_db.session.commit()

    loose.flex_model = {
        "inflexible-production": {"sensor": sensor.id},
        "group": {"asset": street["street"].id},
    }
    loose.generic_asset_type = street["heat"]
    fresh_db.session.commit()

    assert len(report_events_on(fresh_db, street["street"])) == 1


def test_a_group_entry_referenced_by_its_sensor_changing_type_notes_nothing(
    fresh_db, street
):
    """A group may be named by the sensor of its own flex-model entry, rather than by its asset."""
    house = street["house"]
    meter = Sensor(
        "house meter",
        generic_asset=house,
        unit="kW",
        event_resolution=timedelta(minutes=15),
    )
    fresh_db.session.add(meter)
    fresh_db.session.flush()
    house.flex_model = {"sensor": meter.id, "group": {"asset": street["street"].id}}
    for name in ("PV one", "PV two"):
        device = street[name]
        device.flex_model = {**device.flex_model, "group": {"sensor": meter.id}}
    fresh_db.session.commit()
    create_solar_report(street)
    fresh_db.session.commit()

    house.generic_asset_type = street["solar"]
    fresh_db.session.commit()

    assert len(report_events_on(fresh_db, street["street"])) == 1
