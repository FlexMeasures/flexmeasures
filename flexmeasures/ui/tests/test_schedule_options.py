"""Exercise suggestions and additive defaults for manual scheduling."""

import json
from datetime import datetime, timedelta, timezone

from flask import g, url_for
import pytest

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.sensors import create_demo_price_sensor
from flexmeasures.data.models.planning.utils import (
    get_continuous_series_sensor_or_quantity,
)
from flexmeasures.ui.views.assets import scheduling
from sqlalchemy import delete
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def schedule_assets(db, setup_generic_asset_types, setup_accounts):
    parent = GenericAsset(
        name="Scheduling test site",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
    )
    battery = GenericAsset(
        name="Scheduling test battery",
        generic_asset_type=setup_generic_asset_types["battery"],
        owner=setup_accounts["Prosumer"],
    )
    db.session.add_all([parent, battery])
    db.session.commit()
    yield {"test_battery": battery, "troposphere": parent}
    db.session.rollback()
    for asset in (battery, parent):
        sensor_ids = [sensor.id for sensor in asset.sensors]
        db.session.execute(
            delete(TimedBelief).where(TimedBelief.sensor_id.in_(sensor_ids))
        )
        db.session.delete(asset)
    db.session.commit()


def options(client, asset):
    return client.get(
        url_for("AssetSchedulingAPI:schedule_options", id=asset.id),
        query_string={
            "start-time": START.isoformat(),
            "end-time": (START + timedelta(days=1)).isoformat(),
        },
    )


def test_demo_price_profiles_repeat_by_dutch_clock_and_offer_uniform_option(
    db, schedule_assets
):
    asset = schedule_assets["test_battery"]
    start = datetime(2025, 10, 25, 23, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    dynamic = create_demo_price_sensor(asset, start, end)
    uniform = create_demo_price_sensor(asset, start, end, profile="uniform")
    db.session.commit()
    dynamic_values = [
        belief.event_value
        for belief in db.session.query(TimedBelief)
        .filter_by(sensor_id=dynamic.id)
        .order_by(TimedBelief.event_start)
    ]
    uniform_values = [
        belief.event_value
        for belief in db.session.query(TimedBelief)
        .filter_by(sensor_id=uniform.id)
        .order_by(TimedBelief.event_start)
    ]
    assert dynamic_values[:4] == [80, 75, 75, 70]
    assert dynamic_values[25:28] == [80, 75, 70]
    assert len(set(dynamic_values)) > 10
    assert uniform_values == [100] * 48


def test_existing_apis_create_demo_prices_and_save_chosen_defaults(
    db, client, schedule_assets, as_admin
):
    asset = schedule_assets["test_battery"]
    asset.flex_model = {"soc-max": "20 kWh"}
    db.session.commit()
    for key in ("_login_user", "fs_authn_via", "fs_paa", "csrf_valid"):
        g.pop(key, None)
    assert client.get(f"/api/v3_0/assets/{asset.id}").status_code == 200
    created = client.post(
        "/api/v3_0/sensors",
        json={
            "name": "Demo electricity price (Uniform)",
            "generic_asset_id": asset.id,
            "unit": "EUR/MWh",
            "event_resolution": "PT1H",
            "attributes": json.dumps({"demo_data": True, "demo_profile": "uniform"}),
        },
    )
    assert created.status_code == 201
    sensor_id = created.get_json()["id"]
    posted = client.post(
        f"/api/v3_0/sensors/{sensor_id}/data",
        json={
            "start": START.isoformat(),
            "duration": "PT2H",
            "unit": "EUR/MWh",
            "values": [100, 100],
        },
    )
    assert posted.status_code == 200
    assert sensor_id in [
        s["id"] for s in options(client, asset).get_json()["price-sensors"]
    ]
    patched = client.patch(
        f"/api/v3_0/assets/{asset.id}",
        json={
            "flex_context": json.dumps({"consumption-price": {"sensor": sensor_id}}),
            "flex_model": json.dumps({"soc-max": "20 kWh", "power-capacity": "5 kW"}),
        },
    )
    assert patched.status_code == 200
    db.session.refresh(asset)
    assert asset.flex_context["consumption-price"] == {"sensor": sensor_id}
    assert asset.flex_model["soc-max"] == "20 kWh"


def test_suggestions_use_requested_period_and_latest_soc(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    power = Sensor(
        name="power",
        unit="kW",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
    )
    price = Sensor(
        name="price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
    )
    empty_price = Sensor(
        name="empty price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
    )
    soc = Sensor(
        name="stored energy",
        unit="kWh",
        generic_asset=asset,
        event_resolution=timedelta(0),
    )
    db.session.add_all([power, price, empty_price, soc])
    for sensor, instant, value in [
        *((price, START + timedelta(hours=hour), 50) for hour in range(24)),
        (soc, START - timedelta(hours=1), 4),
        (soc, START, 5),
        (soc, START + timedelta(hours=1), 6),
    ]:
        db.session.add(
            TimedBelief(
                sensor=sensor,
                source=setup_sources["Seita"],
                event_start=instant,
                event_value=value,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    response = options(client, asset)
    assert response.status_code == 200
    data = response.get_json()
    assert power.id in [s["id"] for s in data["power-sensors"]]
    assert price.id in [s["id"] for s in data["price-sensors"]]
    assert empty_price.id not in [s["id"] for s in data["price-sensors"]]
    assert data["soc-sensors"][0]["value"] == 5
    assert data["soc-sensors"][0]["event-start"] == START.isoformat()


def test_price_suggestions_allow_gaps_that_scheduler_can_fill(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    price = Sensor(
        name="hourly price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(price)
    for hour in range(-1, 24):
        if hour == 6:
            continue
        db.session.add(
            TimedBelief(
                sensor=price,
                source=setup_sources["Seita"],
                event_start=START + timedelta(minutes=30, hours=hour),
                event_value=50,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    assert price.id in [
        sensor["id"] for sensor in options(client, asset).get_json()["price-sensors"]
    ]

    db.session.add(
        TimedBelief(
            sensor=price,
            source=setup_sources["Seita"],
            event_start=START + timedelta(hours=6, minutes=30),
            event_value=50,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    assert price.id in [
        sensor["id"] for sensor in options(client, asset).get_json()["price-sensors"]
    ]


def test_future_price_events_are_not_available_before_their_belief_time(
    db, client, schedule_assets, setup_sources, as_admin, monkeypatch
):
    asset = schedule_assets["test_battery"]
    price = Sensor(
        name="day-ahead price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(price)
    db.session.flush()
    monkeypatch.setattr(scheduling, "server_now", lambda: START - timedelta(hours=1))
    for hour in range(24):
        db.session.add(
            TimedBelief(
                sensor=price,
                source=setup_sources["Seita"],
                event_start=START + timedelta(hours=hour),
                event_value=50,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    assert price.id not in [
        sensor["id"] for sensor in options(client, asset).get_json()["price-sensors"]
    ]

    asset.flex_context = {"consumption-price": {"sensor": price.id}}
    db.session.commit()
    assert options(client, asset).get_json()["price-available"] is False

    for hour in range(24):
        db.session.add(
            TimedBelief(
                sensor=price,
                source=setup_sources["Seita"],
                event_start=START + timedelta(hours=hour),
                event_value=50,
                belief_horizon=timedelta(days=2),
            )
        )
    db.session.commit()
    assert options(client, asset).get_json()["price-available"] is True


def test_day_ahead_prices_are_available_when_their_knowledge_time_has_passed(
    db, client, schedule_assets, setup_sources, as_admin, monkeypatch
):
    asset = schedule_assets["test_battery"]
    price = Sensor(
        name="day-ahead price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
        knowledge_horizon=(
            x_days_ago_at_y_oclock,
            {"x": 1, "y": 12, "z": "Europe/Paris"},
        ),
    )
    db.session.add(price)
    for hour in range(24):
        db.session.add(
            TimedBelief(
                sensor=price,
                source=setup_sources["Seita"],
                event_start=START + timedelta(hours=hour),
                event_value=50,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    monkeypatch.setattr(scheduling, "server_now", lambda: START + timedelta(hours=12))
    assert price.id in [
        sensor["id"] for sensor in options(client, asset).get_json()["price-sensors"]
    ]
    asset.flex_context = {"consumption-price": {"sensor": price.id}}
    db.session.commit()
    assert options(client, asset).get_json()["price-available"] is True


def test_configured_price_sensor_without_full_coverage_warns_but_allows_run(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    price = Sensor(
        name="partial price",
        unit="EUR/MWh",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(price)
    db.session.flush()
    asset.flex_context = {"consumption-price": {"sensor": price.id}}
    db.session.add(
        TimedBelief(
            sensor=price,
            source=setup_sources["Seita"],
            event_start=START,
            event_value=50,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    data = options(client, asset).get_json()
    assert data["consumption-price"] == {"sensor": price.id}
    assert data["price-available"] is True
    assert data["price-ends-at"] == (START + timedelta(hours=1)).isoformat()
    prices = get_continuous_series_sensor_or_quantity(
        variable_quantity=price,
        unit="EUR/MWh",
        query_window=(START, START + timedelta(days=1)),
        resolution=timedelta(hours=1),
        beliefs_before=datetime.now(timezone.utc),
        fill_sides=True,
    )
    assert prices.iloc[-1] == 50


def test_inherited_settings_avoid_redundant_suggestions(
    db, client, schedule_assets, as_admin
):
    asset = schedule_assets["test_battery"]
    parent = schedule_assets["troposphere"]
    parent.flex_context = {
        "consumption-price": "0.2 EUR/kWh",
        "site-power-capacity": "10 kW",
    }
    asset.parent_asset = parent
    db.session.commit()
    data = options(client, asset).get_json()
    assert data["consumption-price"] == "0.2 EUR/kWh"
    assert data["power-capacity"] == "10 kW"
    assert data["power-capacity-kw"] == 10
    assert data["power-capacity-source"] == "inherited site-power-capacity"
    assert data["is-storage"] is True
    assert data["soc-min"] is None
    assert data["price-sensors"] == []


def test_inherited_price_sensor_is_identified_and_checked_for_coverage(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    parent = schedule_assets["troposphere"]
    price = Sensor(
        name="Site day-ahead price",
        unit="EUR/MWh",
        generic_asset=parent,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(price)
    db.session.flush()
    parent.flex_context = {"consumption-price": {"sensor": price.id}}
    asset.parent_asset = parent
    for hour in range(24):
        db.session.add(
            TimedBelief(
                sensor=price,
                source=setup_sources["Seita"],
                event_start=START + timedelta(hours=hour),
                event_value=50,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    data = options(client, asset).get_json()
    assert data["consumption-price"] == {"sensor": price.id}
    assert data["consumption-price-sensor"] == {
        "id": price.id,
        "name": price.name,
        "unit": price.unit,
        "url": url_for("SensorUI:get", id=price.id),
    }
    assert data["price-available"] is True
    assert data["price-sensors"] == []


def test_starting_soc_is_required_only_for_storage_without_a_configured_value(
    db, client, schedule_assets, setup_generic_asset_types, as_admin
):
    asset = schedule_assets["test_battery"]
    assert options(client, asset).get_json()["requires-soc"] is True

    asset.flex_model = {"soc-at-start": "0 kWh"}
    db.session.commit()
    assert options(client, asset).get_json()["requires-soc"] is False

    asset.flex_model = {}
    asset.generic_asset_type = setup_generic_asset_types["wind"]
    db.session.commit()
    assert options(client, asset).get_json()["requires-soc"] is False


def test_percentage_soc_needs_energy_capacity(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    soc = Sensor(
        name="charge percentage",
        unit="%",
        generic_asset=asset,
        event_resolution=timedelta(0),
    )
    db.session.add(soc)
    db.session.add(
        TimedBelief(
            sensor=soc,
            source=setup_sources["Seita"],
            event_start=START,
            event_value=50,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    assert options(client, asset).get_json()["soc-sensors"] == []
    asset.flex_model = {"soc-max": "20 kWh"}
    db.session.commit()
    suggestion = options(client, asset).get_json()["soc-sensors"][0]
    assert suggestion["value"] == 10
    assert suggestion["unit"] == "kWh"


def test_soc_suggestions_are_no_more_than_one_week_old(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    soc = Sensor(
        name="stored energy",
        unit="kWh",
        generic_asset=asset,
        event_resolution=timedelta(0),
    )
    db.session.add(soc)
    db.session.add(
        TimedBelief(
            sensor=soc,
            source=setup_sources["Seita"],
            event_start=START - timedelta(days=7, seconds=1),
            event_value=4,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    assert options(client, asset).get_json()["soc-sensors"] == []
    db.session.add(
        TimedBelief(
            sensor=soc,
            source=setup_sources["Seita"],
            event_start=START - timedelta(days=7),
            event_value=5,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    assert options(client, asset).get_json()["soc-sensors"][0]["value"] == 5


def test_unreadable_price_sensor_cannot_be_suggested(
    db, client, schedule_assets, setup_accounts, setup_sources, as_prosumer_user1
):
    asset = schedule_assets["test_battery"]
    private_asset = schedule_assets["troposphere"]
    private_asset.owner = setup_accounts["Supplier"]
    price = Sensor(
        name="Private electricity price",
        unit="EUR/MWh",
        generic_asset=private_asset,
        event_resolution=timedelta(hours=1),
    )
    db.session.add(price)
    db.session.add(
        TimedBelief(
            sensor=price,
            source=setup_sources["Seita"],
            event_start=START,
            event_value=50,
            belief_horizon=timedelta(0),
        )
    )
    db.session.commit()
    response = options(client, asset)
    assert response.status_code == 200
    assert price.id not in [
        sensor["id"] for sensor in response.get_json()["price-sensors"]
    ]


def test_newest_price_sensor_is_suggested_when_more_than_ten_match(
    db, client, schedule_assets, setup_sources, as_admin
):
    asset = schedule_assets["test_battery"]
    sensors = []
    for number in range(12):
        sensor = Sensor(
            name=f"Price {number}",
            unit="EUR/MWh",
            generic_asset=asset,
            event_resolution=timedelta(hours=1),
        )
        db.session.add(sensor)
        db.session.flush()
        sensors.append(sensor)
        db.session.add(
            TimedBelief(
                sensor=sensor,
                source=setup_sources["Seita"],
                event_start=START,
                event_value=50,
                belief_horizon=timedelta(0),
            )
        )
    db.session.commit()
    selected_ids = [s["id"] for s in options(client, asset).get_json()["price-sensors"]]
    assert len(selected_ids) == 10
    assert sensors[-1].id == selected_ids[0]
    assert sensors[0].id not in selected_ids
