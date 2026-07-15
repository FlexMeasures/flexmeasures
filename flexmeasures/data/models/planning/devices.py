"""Typed device tracking for schedulers.

Multi-device flex-models describe several kinds of entries (schedulable devices,
stock-only entries carrying SoC parameters for a shared stock, and — in the future —
group entries and converter ports). Historically, each scheduling feature re-derived
an entry's kind from the raw dicts and kept parallel lists aligned by integer position,
which is where several alignment bugs crept in.

This module classifies every entry exactly once, right after flex-config
deserialization, into a :class:`DeviceInventory`: the single source of truth for

- which entries are schedulable devices, and their canonical solver indices,
- which entries only carry SoC parameters for a shared stock (stock-only entries),
- the inflexible devices from the flex-context, in canonical solver order, and
- the stock groups (devices sharing a state-of-charge sensor).

The raw (deserialized) flex-model dicts are kept as-is on each :class:`FlexDevice`,
so downstream code and new flex-model fields need no dataclass changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Any

from marshmallow import ValidationError

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset as Asset


class DeviceRole(Enum):
    """The role a flex-model (or flex-context) entry plays in the scheduling problem.

    Extension points (not yet implemented): GROUP (an entry constraining the aggregate
    power of a set of member devices) and CONVERTER_PORT (a commodity port of a
    multi-commodity converter).
    """

    #: A schedulable flexible device (usually with a power sensor).
    DEVICE = "device"
    #: An entry carrying SoC parameters for a shared stock; not itself scheduled.
    STOCK_ONLY = "stock-only"
    #: An inflexible device from the flex-context (scheduled with a fixed profile).
    INFLEXIBLE = "inflexible"


@dataclass
class FlexDevice:
    """A single classified flex-model (or flex-context) entry.

    Note that ``flex_model`` references the original deserialized dict (it is not a
    copy); code that mutates per-device parameters should work on copies.
    """

    role: DeviceRole
    #: Canonical solver device index; None for stock-only entries.
    index: int | None
    #: The deserialized flex-model entry (with underscore keys); None for inflexible devices.
    flex_model: dict | None
    #: The device's power sensor, resolved from the entry's top-level "sensor" key, else from a nested consumption/production output reference.
    #: None for entries that reference no power sensor at all (e.g. asset-only entries).
    power_sensor: Sensor | None
    #: The device's asset, resolved from the power sensor or the entry's "asset" key.
    asset: Asset | None
    commodity: str = "electricity"
    #: Key of the stock this device draws from: the id of its state-of-charge sensor, or a unique negative synthetic key for devices without one.
    #: None for inflexible devices.
    stock_key: int | None = None

    @property
    def sensor_id(self) -> int | None:
        if self.power_sensor is not None:
            return getattr(self.power_sensor, "id", None)
        return None

    @property
    def state_of_charge(self) -> Any:
        # A flex-model entry always has a dict; this None check is a precaution for inflexible devices, which have no flex-model entry.
        if self.flex_model is None:
            return None
        return self.flex_model.get("state_of_charge")

    @property
    def consumption_sensor(self) -> Sensor | None:
        return _resolve_output_sensor(self.flex_model, "consumption")

    @property
    def production_sensor(self) -> Sensor | None:
        return _resolve_output_sensor(self.flex_model, "production")


def _resolve_output_sensor(flex_model: dict | None, output_field: str) -> Sensor | None:
    """Resolve the sensor of a nested consumption/production output reference."""
    if flex_model is None:
        return None
    output_ref = flex_model.get(output_field)
    if isinstance(output_ref, dict):
        output_sensor = output_ref.get("sensor")
        if isinstance(output_sensor, Sensor):
            return output_sensor
        # Tolerate SensorReference-like objects without importing schema modules.
        if isinstance(getattr(output_sensor, "sensor", None), Sensor):
            return output_sensor.sensor
    return None


def _resolve_power_sensor(flex_model: dict) -> Sensor | None:
    """Resolve a flex-model entry's power sensor.

    The top-level "sensor" key takes precedence. Devices that reference their power
    sensor only via a nested output reference (e.g. ``{"consumption": {"sensor": N}}``)
    resolve to that output sensor, so they are recognized as schedulable devices
    (rather than being misclassified as stock-only entries and silently dropped).
    """
    sensor = flex_model.get("sensor")
    if sensor is not None:
        return sensor
    for output_field in ("consumption", "production"):
        output_sensor = _resolve_output_sensor(flex_model, output_field)
        if output_sensor is not None:
            return output_sensor
    return None


def _resolve_stock_key(state_of_charge: Any) -> int | None:
    """Resolve a state-of-charge reference to a stock key (the SoC sensor id).

    Only a sensor reference can link devices into a shared stock. A
    state-of-charge given as a value or time series (e.g. a list of timed values)
    resolves to None: the device keeps a stock of its own.
    """
    if state_of_charge is None:
        return None
    if hasattr(state_of_charge, "id"):
        return state_of_charge.id
    key = state_of_charge
    if isinstance(state_of_charge, dict) and "sensor" in state_of_charge:
        sensor = state_of_charge["sensor"]
        key = sensor.id if hasattr(sensor, "id") else sensor
    try:
        hash(key)
    except TypeError:
        return None
    return key


#: Flex-model fields that make a device entry (with a state-of-charge sensor)
#: also carry the SoC parameters of its stock.
SOC_PARAM_FIELDS = ("soc_at_start", "soc_min", "soc_max", "soc_targets")


@dataclass
class DeviceInventory:
    """All devices of a scheduling problem, classified once, in canonical solver order.

    The canonical device enumeration is:

    1. flexible devices (flex-model entries with role DEVICE), in flex-model order,
    2. top-level (electricity) inflexible-device-sensors from the flex-context, in order,
    3. each commodity context's own inflexible-device-sensors, in the order the
       commodity contexts are given.

    This is the one enumeration both `_prepare()` and the result mapping rely on,
    so they cannot drift apart.
    """

    #: All flex-model entries, in their original order (including stock-only entries).
    entries: list[FlexDevice] = field(default_factory=list)
    #: The schedulable devices; ``devices[d].index == d``.
    devices: list[FlexDevice] = field(default_factory=list)
    #: The inflexible devices from the flex-context, with indices following the devices.
    inflexible_devices: list[FlexDevice] = field(default_factory=list)
    #: SoC parameters per stock key. Keys are shared with :attr:`stock_groups`.
    stock_entries: dict[int, dict] = field(default_factory=dict)
    is_single_sensor_mode: bool = False

    @classmethod
    def from_flex_config(
        cls,
        flex_model: list[dict] | dict,
        flex_context: dict | None = None,
        sensor: Sensor | None = None,
    ) -> "DeviceInventory":
        """Classify a deserialized flex-model (and flex-context) into an inventory.

        :param flex_model: The deserialized flex-model: a dict (single-sensor mode,
                           in which case ``sensor`` is the device's power sensor)
                           or a list of entry dicts (multi-device mode).
        :param flex_context: The deserialized flex-context, used for the inflexible
                             devices (top-level and per commodity context).
        :param sensor: The scheduler's target sensor (single-sensor mode only).
        """
        flex_context = flex_context or {}
        is_single_sensor_mode = not isinstance(flex_model, list)
        flex_model_list = [flex_model] if is_single_sensor_mode else flex_model

        inventory = cls(is_single_sensor_mode=is_single_sensor_mode)

        # One counter yields the synthetic stock keys for devices without a
        # state-of-charge sensor, so stock_entries and stock_groups always share keys.
        synthetic_stock_key = -len(flex_model_list)

        def register_stock_params(stock_key: int, fm: dict) -> None:
            """Register the flex-model entry holding a stock's SoC parameters, failing fast on conflicts."""
            existing = inventory.stock_entries.get(stock_key)
            if existing is not None and existing is not fm:
                raise ValidationError(
                    f"Multiple flex-model entries define state-of-charge parameters for the same stock"
                    f" (state-of-charge sensor {stock_key}). Please define them on a single entry."
                )
            inventory.stock_entries[stock_key] = fm

        for fm in flex_model_list:
            if is_single_sensor_mode:
                power_sensor = sensor
            else:
                power_sensor = _resolve_power_sensor(fm)
            state_of_charge = fm.get("state_of_charge")
            stock_key = _resolve_stock_key(state_of_charge)

            # Stock-only entry: SoC parameters for a shared stock, but no power sensor
            # (only in multi-device mode; in single-sensor mode the power sensor is the
            # scheduler's target sensor rather than a flex-model field).
            if (
                not is_single_sensor_mode
                and power_sensor is None
                and state_of_charge is not None
            ):
                if stock_key is None:
                    stock_key = synthetic_stock_key
                    synthetic_stock_key += 1
                entry = FlexDevice(
                    role=DeviceRole.STOCK_ONLY,
                    index=None,
                    flex_model=fm,
                    power_sensor=None,
                    asset=fm.get("asset"),
                    stock_key=stock_key,
                )
                inventory.entries.append(entry)
                register_stock_params(stock_key, fm)
                continue

            # Device entry.
            if stock_key is None:
                stock_key = synthetic_stock_key
                synthetic_stock_key += 1
                # A device without a state-of-charge *sensor* (it may still define a
                # state of charge as a value or time series) keeps its own SoC
                # parameters, under its synthetic stock key.
                register_stock_params(stock_key, fm)
            elif any(param in fm for param in SOC_PARAM_FIELDS):
                # A device entry may also carry the SoC parameters of its stock itself,
                # as long as only one entry per stock does.
                register_stock_params(stock_key, fm)

            device = FlexDevice(
                role=DeviceRole.DEVICE,
                index=len(inventory.devices),
                flex_model=fm,
                power_sensor=power_sensor,
                asset=(
                    power_sensor.asset if power_sensor is not None else fm.get("asset")
                ),
                commodity=fm.get("commodity", "electricity"),
                stock_key=stock_key,
            )
            inventory.entries.append(device)
            inventory.devices.append(device)

        # Inflexible devices from the flex-context: top-level (electricity) sensors
        # first, then each commodity context's own sensors, in context order.
        index = len(inventory.devices)
        for inflexible_sensor in flex_context.get("inflexible_device_sensors", []):
            inventory.inflexible_devices.append(
                FlexDevice(
                    role=DeviceRole.INFLEXIBLE,
                    index=index,
                    flex_model=None,
                    power_sensor=inflexible_sensor,
                    asset=getattr(inflexible_sensor, "asset", None),
                    commodity="electricity",
                )
            )
            index += 1
        for commodity_context in flex_context.get("commodity_contexts", []):
            commodity = commodity_context["commodity"]
            for inflexible_sensor in commodity_context.get(
                "inflexible_device_sensors", []
            ):
                inventory.inflexible_devices.append(
                    FlexDevice(
                        role=DeviceRole.INFLEXIBLE,
                        index=index,
                        flex_model=None,
                        power_sensor=inflexible_sensor,
                        asset=getattr(inflexible_sensor, "asset", None),
                        commodity=commodity,
                    )
                )
                index += 1

        assert all(
            device.index == d for d, device in enumerate(inventory.devices)
        ), "Device indices must match their position among the schedulable devices."
        return inventory

    @property
    def num_flexible(self) -> int:
        """The number of schedulable (flexible) devices."""
        return len(self.devices)

    @property
    def num_scheduled(self) -> int:
        """The number of devices in the optimization problem (flexible + inflexible)."""
        return len(self.devices) + len(self.inflexible_devices)

    def by_index(self, d: int) -> FlexDevice:
        """Return the device with canonical solver index ``d`` (flexible or inflexible)."""
        if d < len(self.devices):
            return self.devices[d]
        return self.inflexible_devices[d - len(self.devices)]

    def by_sensor_id(self, sensor_id: int) -> list[FlexDevice]:
        """Return the flexible devices whose power sensor has the given id."""
        return [device for device in self.devices if device.sensor_id == sensor_id]

    @cached_property
    def stock_groups(self) -> dict[int, list[int]]:
        """Map each stock key to the indices of the devices drawing from that stock.

        Devices sharing a state-of-charge sensor are grouped together; devices without
        one form singleton groups under their synthetic (negative) stock key.
        """
        groups: dict[int, list[int]] = {}
        for device in self.devices:
            groups.setdefault(device.stock_key, []).append(device.index)
        return groups

    def stock_params(self, stock_key: int) -> dict | None:
        """Return the flex-model entry holding the SoC parameters of the given stock."""
        return self.stock_entries.get(stock_key)

    @cached_property
    def commodity_to_devices(self) -> dict[str, list[int]]:
        """Map each commodity to its device indices, in canonical solver order."""
        mapping: dict[str, list[int]] = {}
        for device in self.devices:
            mapping.setdefault(device.commodity, []).append(device.index)
        # Inflexible devices are electricity by default, so the electricity group
        # exists even when empty.
        mapping.setdefault("electricity", [])
        for device in self.inflexible_devices:
            mapping.setdefault(device.commodity, []).append(device.index)
        return mapping

    @property
    def inflexible_sensors(self) -> list[Sensor]:
        """The inflexible devices' power sensors, in canonical solver order.

        Inflexible devices are constructed from the flex-context's sensors, so their power sensor is always set.
        """
        return [device.power_sensor for device in self.inflexible_devices]

    @property
    def power_sensors(self) -> list[Sensor | None]:
        """The flexible devices' power sensors, by device index."""
        return [device.power_sensor for device in self.devices]

    @property
    def assets(self) -> list[Asset | None]:
        """The flexible devices' assets, by device index."""
        return [device.asset for device in self.devices]

    @property
    def device_flex_models(self) -> list[dict]:
        """The flexible devices' flex-model entries, by device index."""
        return [device.flex_model for device in self.devices]
