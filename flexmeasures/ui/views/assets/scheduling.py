"""Lazy suggestions and narrowly scoped defaults for the manual scheduling dialog."""

from datetime import timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from flask import url_for
from marshmallow import ValidationError
from sqlalchemy import or_, select
from flask_security import current_user

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.planning.storage import storage_asset_types
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.generic_assets import patch_asset
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.ui.utils.auth_utils import user_can_access
from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import is_energy_price_unit


def sensor_option(sensor):
    return dict(
        id=sensor.id,
        name=sensor.name,
        unit=sensor.unit,
        url=url_for("SensorUI:get", id=sensor.id),
    )


def last_price_end(sensor, start_time, end_time, belief_time):
    """Find the end of the latest known price event within the schedule period."""
    resolution = sensor.event_resolution
    if resolution <= timedelta(0):
        return None
    beliefs = sensor.search_beliefs(
        event_starts_after=start_time,
        event_ends_before=end_time,
        beliefs_before=belief_time,
    )
    if beliefs.empty:
        return None
    return beliefs.index.get_level_values("event_start").max() + resolution


def price_covers_schedule(sensor, start_time, end_time, belief_time):
    """Report whether the scheduler can use at least one known price event."""
    return last_price_end(sensor, start_time, end_time, belief_time) is not None


def readable_price_candidates(start_time, end_time):
    """Filter price candidates by readable organisation and event window in SQL."""
    account_ids = [current_user.account_id]
    if current_user.has_role("consultant"):
        client_ids = select(Account.id).where(
            Account.consultancy_account_id == current_user.account_id
        )
        account_ids.extend(db.session.scalars(client_ids).all())
    scope = or_(
        GenericAsset.account_id.in_(account_ids), GenericAsset.account_id.is_(None)
    )
    if current_user.has_role("admin"):
        scope = True
    unit_query = (
        select(Sensor.unit)
        .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
        .where(scope)
        .distinct()
    )
    price_units = [
        unit for unit in db.session.scalars(unit_query) if is_energy_price_unit(unit)
    ]
    if not price_units:
        return []
    candidate_ids = (
        select(Sensor.id)
        .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
        .join(TimedBelief, TimedBelief.sensor_id == Sensor.id)
        .where(
            scope,
            Sensor.unit.in_(price_units),
            TimedBelief.event_start < end_time,
            TimedBelief.event_start + Sensor.event_resolution > start_time,
        )
        .distinct()
    )
    return db.session.scalars(
        select(Sensor).where(Sensor.id.in_(candidate_ids)).order_by(Sensor.id.desc())
    )


def power_capacity_option(model, context):
    """Show the effective power limit and its source before it is overridden."""
    capacity_keys = (
        ("power-capacity", "this asset’s power-capacity"),
        ("consumption-capacity", "this asset’s consumption-capacity"),
        ("production-capacity", "this asset’s production-capacity"),
    )
    capacity, source = next(
        (
            (model[key], label)
            for key, label in capacity_keys
            if model.get(key) is not None
        ),
        (context.get("site-power-capacity"), "inherited site-power-capacity"),
    )
    try:
        capacity_kw = QuantityField("kW", return_magnitude=True).deserialize(capacity)
    except ValidationError:
        capacity_kw = None
    return capacity, capacity_kw, source if capacity is not None else None


def schedule_options(asset, start_time, end_time):
    """Find readable candidates only when the dialog requests them."""
    belief_time = server_now()
    context = asset.get_flex_context()
    consumption_price = context.get("consumption-price")
    if consumption_price is None and context.get("consumption-price-sensor"):
        consumption_price = {"sensor": context["consumption-price-sensor"]}
    price_available = True
    price_ends_at = None
    consumption_price_sensor = None
    if isinstance(consumption_price, dict) and "sensor" in consumption_price:
        sensor = db.session.get(Sensor, consumption_price["sensor"])
        if sensor and user_can_access(sensor, "read") and sensor.measures_energy_price:
            consumption_price_sensor = sensor_option(sensor)
        last_end = (
            last_price_end(sensor, start_time, end_time, belief_time)
            if consumption_price_sensor
            else None
        )
        price_available = last_end is not None
        if last_end is not None and last_end < end_time:
            price_ends_at = last_end.isoformat()
    power_sensors = [
        sensor_option(sensor)
        for sensor in asset.sensors
        if sensor.measures_power and user_can_access(sensor, "read")
    ]
    prices = []
    if consumption_price is None or not price_available or price_ends_at:
        for sensor in readable_price_candidates(start_time, end_time):
            if not user_can_access(sensor, "read"):
                continue
            if price_covers_schedule(sensor, start_time, end_time, belief_time):
                prices.append(sensor_option(sensor))
                if len(prices) == 10:
                    break
    soc_sensors = soc_options(asset, start_time)
    model = asset.flex_model
    capacity, capacity_kw, capacity_source = power_capacity_option(model, context)
    try:
        soc_max = QuantityField("kWh", return_magnitude=True).deserialize(
            model.get("soc-max")
        )
    except ValidationError:
        soc_max = None
    return dict(
        power_sensors=power_sensors,
        price_sensors=prices,
        consumption_price=consumption_price,
        consumption_price_sensor=consumption_price_sensor,
        price_available=price_available,
        price_ends_at=price_ends_at,
        power_capacity=capacity,
        power_capacity_kw=capacity_kw,
        power_capacity_source=capacity_source,
        soc_min=model.get("soc-min"),
        is_storage=asset.asset_type.name in storage_asset_types,
        soc_sensors=soc_sensors,
        soc_max=soc_max,
        configured_soc_sensor=(
            model.get("state-of-charge", {}).get("sensor")
            if isinstance(model.get("state-of-charge"), dict)
            else None
        ),
        requires_soc=(
            asset.asset_type.name in storage_asset_types
            and model.get("soc-at-start") is None
            and model.get("state-of-charge") is None
        ),
        timezone=asset.timezone,
        can_save=user_can_access(asset, "edit-flex-config"),
        can_create_demo_prices=user_can_access(asset, "edit-sensors"),
    )


def soc_options(asset, start_time):
    """Offer readable state-of-charge snapshots at or before the start."""
    soc_sensors = []
    configured_soc = asset.flex_model.get("state-of-charge")
    configured_id = (
        configured_soc.get("sensor") if isinstance(configured_soc, dict) else None
    )
    candidates = list(asset.sensors)
    if configured_id and all(s.id != configured_id for s in candidates):
        configured_sensor = db.session.get(Sensor, configured_id)
        if configured_sensor:
            candidates.insert(0, configured_sensor)
    for sensor in sorted(candidates, key=lambda s: s.id != configured_id):
        if (
            not user_can_access(sensor, "read")
            or sensor.event_resolution != timedelta(0)
            or not (sensor.measures_energy or sensor.unit == "%")
        ):
            continue
        belief = db.session.scalars(
            select(TimedBelief)
            .where(
                TimedBelief.sensor_id == sensor.id,
                TimedBelief.event_start >= start_time - timedelta(days=7),
                TimedBelief.event_start <= start_time,
            )
            .order_by(TimedBelief.event_start.desc(), TimedBelief.belief_horizon.asc())
            .limit(1)
        ).first()
        if belief is not None and isfinite(belief.event_value):
            value = belief.event_value
            unit = sensor.unit
            if unit == "%":
                try:
                    maximum = QuantityField("kWh", return_magnitude=True).deserialize(
                        asset.flex_model.get("soc-max")
                    )
                except ValidationError:
                    continue
                if not isfinite(maximum) or maximum <= 0:
                    continue
                value = value / 100 * maximum
                unit = "kWh"
            option = sensor_option(sensor)
            option["unit"] = unit
            soc_sensors.append(
                dict(
                    **option,
                    value=value,
                    event_start=belief.event_start.astimezone(
                        ZoneInfo(sensor.timezone)
                    ).isoformat(),
                    timezone=sensor.timezone,
                )
            )
    return soc_sensors


def validate_soc_sensor_to_save(asset, sensor_id):
    """Validate a state-of-charge sensor proposed as a permanent default."""
    if not isinstance(sensor_id, int) or isinstance(sensor_id, bool):
        raise ValidationError("state_of_charge_sensor must be a sensor ID.")
    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        raise ValidationError("State-of-charge sensor does not exist.")
    check_access(sensor, "read")
    if sensor.generic_asset_id != asset.id or not (
        sensor.measures_energy or sensor.unit == "%"
    ):
        raise ValidationError("Choose a state-of-charge sensor on this asset.")
    if asset.flex_model.get("state-of-charge") is not None:
        raise ValidationError(
            "State of charge is already configured. Reload the dialog."
        )


def save_schedule_defaults(asset, data):
    """Merge only missing wizard defaults, preserving concurrent asset edits."""
    check_access(asset, "edit-flex-config")
    if not isinstance(data, dict) or set(data) - {
        "consumption_price_sensor",
        "power_capacity",
        "state_of_charge_sensor",
    }:
        raise ValidationError(
            "Only consumption_price_sensor, power_capacity and state_of_charge_sensor are accepted."
        )
    asset = db.session.scalars(
        select(GenericAsset)
        .where(GenericAsset.id == asset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    changes = {}
    if "consumption_price_sensor" in data:
        sensor_id = data["consumption_price_sensor"]
        if not isinstance(sensor_id, int) or isinstance(sensor_id, bool):
            raise ValidationError("consumption_price_sensor must be a sensor ID.")
        sensor = db.session.get(Sensor, sensor_id)
        check_access(sensor, "read")
        if not sensor.measures_energy_price:
            raise ValidationError("Choose a sensor measuring energy prices.")
        context = asset.get_flex_context()
        if (
            context.get("consumption-price") is not None
            or context.get("consumption-price-sensor") is not None
        ):
            raise ValidationError(
                "A consumption price is already configured. Reload the dialog."
            )
        changes["flex_context"] = dict(
            asset.flex_context, **{"consumption-price": {"sensor": sensor.id}}
        )
    if "power_capacity" in data:
        if not isinstance(data["power_capacity"], str):
            raise ValidationError(
                "Power capacity must be a quantity with a unit, such as 5 kW."
            )
        capacity = QuantityField("MW", return_magnitude=True).deserialize(
            data["power_capacity"]
        )
        if not isfinite(capacity) or capacity <= 0:
            raise ValidationError(
                "Power capacity must be finite and greater than zero."
            )
        changes["flex_model"] = dict(
            asset.flex_model, **{"power-capacity": data["power_capacity"]}
        )
    if "state_of_charge_sensor" in data:
        sensor_id = data["state_of_charge_sensor"]
        validate_soc_sensor_to_save(asset, sensor_id)
        changes["flex_model"] = dict(
            changes.get("flex_model", asset.flex_model),
            **{"state-of-charge": {"sensor": sensor_id}},
        )
    patch_asset(asset, changes)
    db.session.commit()
    return {"message": "Scheduling defaults saved on the asset."}
