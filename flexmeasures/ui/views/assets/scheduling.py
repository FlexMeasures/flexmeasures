"""Lazy suggestions and narrowly scoped defaults for the manual scheduling dialog."""

from datetime import timedelta
from math import isfinite

from flask import url_for
from marshmallow import ValidationError
from sqlalchemy import select

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.planning.storage import storage_asset_types
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.generic_assets import patch_asset
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.ui.utils.auth_utils import user_can_access


def sensor_option(sensor):
    return dict(
        id=sensor.id,
        name=sensor.name,
        unit=sensor.unit,
        url=url_for("SensorUI:get", id=sensor.id),
    )


def price_covers_schedule(sensor, start_time, end_time):
    """Check that price intervals cover the complete half-open schedule period."""
    resolution = sensor.event_resolution
    if resolution <= timedelta(0):
        return False
    event_starts = db.session.scalars(
        select(TimedBelief.event_start)
        .where(
            TimedBelief.sensor_id == sensor.id,
            TimedBelief.event_start > start_time - resolution,
            TimedBelief.event_start < end_time,
        )
        .distinct()
        .order_by(TimedBelief.event_start)
    )
    covered_until = start_time
    for event_start in event_starts:
        if event_start > covered_until:
            return False
        covered_until = max(covered_until, event_start + resolution)
        if covered_until >= end_time:
            return True
    return False


def schedule_options(asset, start_time, end_time):
    """Find readable candidates only when the dialog requests them."""
    context = asset.get_flex_context()
    consumption_price = context.get("consumption-price")
    if consumption_price is None and context.get("consumption-price-sensor"):
        consumption_price = {"sensor": context["consumption-price-sensor"]}
    price_available = True
    consumption_price_sensor = None
    if isinstance(consumption_price, dict) and "sensor" in consumption_price:
        sensor = db.session.get(Sensor, consumption_price["sensor"])
        if sensor and user_can_access(sensor, "read") and sensor.measures_energy_price:
            consumption_price_sensor = sensor_option(sensor)
        price_available = bool(
            consumption_price_sensor
            and price_covers_schedule(sensor, start_time, end_time)
        )
    power_sensors = [
        sensor_option(sensor)
        for sensor in asset.sensors
        if sensor.measures_power and user_can_access(sensor, "read")
    ]
    prices = []
    if consumption_price is None:
        for sensor in db.session.scalars(select(Sensor).order_by(Sensor.id)):
            if not sensor.measures_energy_price or not user_can_access(sensor, "read"):
                continue
            if price_covers_schedule(sensor, start_time, end_time):
                prices.append(sensor_option(sensor))
                if len(prices) == 10:
                    break
    soc_sensors = soc_options(asset, start_time)
    model = asset.flex_model
    return dict(
        power_sensors=power_sensors,
        price_sensors=prices,
        consumption_price=consumption_price,
        consumption_price_sensor=consumption_price_sensor,
        price_available=price_available,
        power_capacity=model.get(
            "power-capacity",
            model.get(
                "consumption-capacity",
                model.get("production-capacity", context.get("site-power-capacity")),
            ),
        ),
        soc_sensors=soc_sensors,
        requires_soc=(
            asset.asset_type.name in storage_asset_types
            and model.get("soc-at-start") is None
        ),
        timezone=asset.timezone,
        can_save=user_can_access(asset, "edit-flex-config"),
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
                    event_start=belief.event_start.isoformat(),
                )
            )
    return soc_sensors


def save_schedule_defaults(asset, data):
    """Merge only missing wizard defaults, preserving concurrent asset edits."""
    check_access(asset, "edit-flex-config")
    if not isinstance(data, dict) or set(data) - {
        "consumption_price_sensor",
        "power_capacity",
    }:
        raise ValidationError(
            "Only consumption_price_sensor and power_capacity are accepted."
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
        if any(
            asset.flex_model.get(key) is not None
            for key in ("power-capacity", "consumption-capacity", "production-capacity")
        ):
            raise ValidationError(
                "A power capacity is already configured. Reload the dialog."
            )
        changes["flex_model"] = dict(
            asset.flex_model, **{"power-capacity": data["power_capacity"]}
        )
    patch_asset(asset, changes)
    db.session.commit()
    return {"message": "Scheduling defaults saved on the asset."}
