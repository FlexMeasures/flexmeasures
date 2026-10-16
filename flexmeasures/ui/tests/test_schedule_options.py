"""Exercise suggestions and additive defaults for manual scheduling."""

from datetime import datetime, timedelta, timezone

from flask import url_for
import pytest

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.sensors import create_demo_price_sensor
from flexmeasures.ui.views.assets import scheduling
from sqlalchemy import delete

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
        url_for("AssetCrudUI:schedule_options", id=asset.id),
        query_string={
            "start_time": START.isoformat(),
            "end_time": (START + timedelta(days=1)).isoformat(),
        },
    )


def test_demo_prices_create_reusable_sensor_with_known_full_period(
    db, client, schedule_assets, as_admin
):
    asset = schedule_assets["test_battery"]
    start = START + timedelta(minutes=30)
    end = START + timedelta(hours=2, minutes=15)
    response = client.post(
        url_for("AssetCrudUI:demo_prices", id=asset.id),
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
    )
    assert response.status_code == 201
    sensor = db.session.get(Sensor, response.get_json()["id"])
    assert sensor.generic_asset_id == asset.id
    assert sensor.attributes["demo_data"] is True
    assert sensor.attributes["demo_profile"] == "nl_october_day"
    assert sensor.unit == "EUR/MWh"
    beliefs = (
        db.session.query(TimedBelief)
        .filter(TimedBelief.sensor_id == sensor.id)
        .order_by(TimedBelief.event_start)
        .all()
    )
    assert [b.event_start for b in beliefs] == [
        START,
        START + timedelta(hours=1),
        START + timedelta(hours=2),
    ]
    assert [b.event_value for b in beliefs] == [80, 75, 70]
    assert all(b.belief_time <= datetime.now(timezone.utc) for b in beliefs)
    assert all(b.source.type == "demo" for b in beliefs)
    assert scheduling.price_covers_schedule(
        sensor, start, end, datetime.now(timezone.utc)
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


def test_demo_prices_accepts_uniform_profile(db, client, schedule_assets, as_admin):
    asset = schedule_assets["test_battery"]
    response = client.post(
        url_for("AssetCrudUI:demo_prices", id=asset.id),
        json={
            "start_time": START.isoformat(),
            "end_time": (START + timedelta(hours=2)).isoformat(),
            "profile": "uniform",
        },
    )
    assert response.status_code == 201
    sensor = db.session.get(Sensor, response.get_json()["id"])
    assert sensor.attributes["demo_profile"] == "uniform"
    assert [
        belief.event_value
        for belief in db.session.query(TimedBelief).filter_by(sensor_id=sensor.id)
    ] == [100, 100]


def test_demo_prices_refuses_configured_price_and_overlong_period(
    db, client, schedule_assets, as_admin
):
    asset = schedule_assets["test_battery"]
    endpoint = url_for("AssetCrudUI:demo_prices", id=asset.id)
    response = client.post(
        endpoint,
        json={
            "start_time": START.isoformat(),
            "end_time": (START + timedelta(days=32)).isoformat(),
        },
    )
    assert response.status_code == 422
    asset.flex_context = {"consumption-price": "100 EUR/MWh"}
    db.session.commit()
    response = client.post(
        endpoint,
        json={
            "start_time": START.isoformat(),
            "end_time": (START + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 422
    assert not db.session.query(Sensor).filter_by(generic_asset_id=asset.id).count()


def test_demo_prices_requires_asset_sensor_edit_permission(
    db, client, schedule_assets, setup_accounts, as_prosumer_user1
):
    asset = schedule_assets["test_battery"]
    asset.owner = setup_accounts["Supplier"]
    db.session.commit()
    response = client.post(
        url_for("AssetCrudUI:demo_prices", id=asset.id),
        json={
            "start_time": START.isoformat(),
            "end_time": (START + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 403
    assert not db.session.query(Sensor).filter_by(generic_asset_id=asset.id).count()


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
    assert power.id in [s["id"] for s in data["power_sensors"]]
    assert price.id in [s["id"] for s in data["price_sensors"]]
    assert empty_price.id not in [s["id"] for s in data["price_sensors"]]
    assert data["soc_sensors"][0]["value"] == 5
    assert data["soc_sensors"][0]["event_start"] == START.isoformat()


def test_price_suggestions_require_every_interval_and_allow_overlap_at_start(
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
    assert price.id not in [
        sensor["id"] for sensor in options(client, asset).get_json()["price_sensors"]
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
        sensor["id"] for sensor in options(client, asset).get_json()["price_sensors"]
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
        sensor["id"] for sensor in options(client, asset).get_json()["price_sensors"]
    ]

    asset.flex_context = {"consumption-price": {"sensor": price.id}}
    db.session.commit()
    assert options(client, asset).get_json()["price_available"] is False

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
    assert options(client, asset).get_json()["price_available"] is True


def test_configured_price_sensor_without_full_coverage_is_reported(
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
    assert data["consumption_price"] == {"sensor": price.id}
    assert data["price_available"] is False


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
    assert data["consumption_price"] == "0.2 EUR/kWh"
    assert data["power_capacity"] == "10 kW"
    assert data["price_sensors"] == []


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
    assert data["consumption_price"] == {"sensor": price.id}
    assert data["consumption_price_sensor"] == {
        "id": price.id,
        "name": price.name,
        "unit": price.unit,
        "url": url_for("SensorUI:get", id=price.id),
    }
    assert data["price_available"] is True
    assert data["price_sensors"] == []


def test_starting_soc_is_required_only_for_storage_without_a_configured_value(
    db, client, schedule_assets, setup_generic_asset_types, as_admin
):
    asset = schedule_assets["test_battery"]
    assert options(client, asset).get_json()["requires_soc"] is True

    asset.flex_model = {"soc-at-start": "0 kWh"}
    db.session.commit()
    assert options(client, asset).get_json()["requires_soc"] is False

    asset.flex_model = {}
    asset.generic_asset_type = setup_generic_asset_types["wind"]
    db.session.commit()
    assert options(client, asset).get_json()["requires_soc"] is False


def test_defaults_preserve_config_and_refuse_overwrite(
    db, client, schedule_assets, as_admin
):
    asset = schedule_assets["test_battery"]
    asset.flex_model = {"soc-min": "1 kWh"}
    db.session.commit()
    url = url_for("AssetCrudUI:schedule_defaults", id=asset.id)
    response = client.post(url, json={"power_capacity": "5 kW"})
    assert response.status_code == 200
    db.session.refresh(asset)
    assert asset.flex_model == {"soc-min": "1 kWh", "power-capacity": "5 kW"}
    assert client.post(url, json={"power_capacity": "6 kW"}).status_code == 422
    db.session.refresh(asset)
    assert asset.flex_model["power-capacity"] == "5 kW"


@pytest.mark.parametrize("capacity", ["-1 kW", "0 kW", "5 kWh", {"sensor": 1}, None])
def test_defaults_reject_invalid_capacity(
    db, client, schedule_assets, as_admin, capacity
):
    asset = schedule_assets["test_battery"]
    response = client.post(
        url_for("AssetCrudUI:schedule_defaults", id=asset.id),
        json={"power_capacity": capacity},
    )
    assert response.status_code == 422
    db.session.refresh(asset)
    assert "power-capacity" not in asset.flex_model


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
    assert options(client, asset).get_json()["soc_sensors"] == []
    asset.flex_model = {"soc-max": "20 kWh"}
    db.session.commit()
    suggestion = options(client, asset).get_json()["soc_sensors"][0]
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
    assert options(client, asset).get_json()["soc_sensors"] == []
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
    assert options(client, asset).get_json()["soc_sensors"][0]["value"] == 5


def test_unreadable_price_sensor_cannot_be_suggested_or_saved(
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
        sensor["id"] for sensor in response.get_json()["price_sensors"]
    ]
    response = client.post(
        url_for("AssetCrudUI:schedule_defaults", id=asset.id),
        json={"consumption_price_sensor": price.id},
    )
    assert response.status_code == 403
    db.session.refresh(asset)
    assert "consumption-price" not in asset.flex_context
