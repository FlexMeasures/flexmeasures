"""Typed device tracking for schedulers.

Multi-device flex-models describe several kinds of entries (schedulable devices,
stock-only entries carrying SoC parameters for a shared stock,
group entries carrying constraints on the aggregate power of a set of member devices,
and — in the future — converter ports). Historically, each scheduling feature re-derived
an entry's kind from the raw dicts and kept parallel lists aligned by integer position,
which is where several alignment bugs crept in.

This module classifies every entry exactly once, right after flex-config
deserialization, into a :class:`DeviceInventory`: the single source of truth for

- which entries are schedulable devices, and their canonical solver indices,
- which entries only carry SoC parameters for a shared stock (stock-only entries),
- which entries are group entries, and which devices belong to each group,
- the inflexible devices from the flex-context, in canonical solver order, and
- the stock groups (devices sharing a state-of-charge sensor).

The raw (deserialized) flex-model dicts are kept as-is on each :class:`FlexDevice`,
so downstream code and new flex-model fields need no dataclass changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Any

from marshmallow import ValidationError

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset as Asset


class DeviceRole(Enum):
    """The role a flex-model (or flex-context) entry plays in the scheduling problem.

    Converter ports (the commodity ports of a multi-commodity converter,
    such as a CHP unit) are DEVICE entries carrying a ``coupling`` field;
    see :attr:`DeviceInventory.coupling_groups`.
    GROUP entries constrain the aggregate power of a set of member devices.
    """

    #: A schedulable flexible device (usually with a power sensor).
    DEVICE = "device"
    #: An entry carrying SoC parameters for a shared stock; not itself scheduled.
    STOCK_ONLY = "stock-only"
    #: An entry constraining the aggregate power of a set of member devices; not itself scheduled.
    GROUP = "group"
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
    #: Name of the coupling group this device belongs to (converter ports of one converter share a coupling name).
    #: None for uncoupled devices.
    coupling: str | None = None
    #: Signed internal coupling coefficient: positive for input (consuming) ports, negative for output (producing) ports.
    #: Meaningless (1.0) for uncoupled devices.
    coupling_coefficient: float = 1.0
    #: Signed per-port no-load base (in MW), gated by the group's on/off binary when the group is unit-committed.
    #: Follows the same sign convention as the coefficient; 0.0 when no ``coupling-base`` is given.
    coupling_base: float = 0.0
    #: Group minimum marginal level (in MW), declared on the reference port (|coefficient| == 1). None when not set.
    coupling_min: float | None = None
    #: The reference port's power capacity (in MW), used as the group's maximum marginal level. None when not resolvable.
    coupling_max: float | None = None

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

    @property
    def group_key(self) -> tuple[str, int] | None:
        """The key of the group this entry belongs to (via its "group" field), if any."""
        return resolve_group_key(self.flex_model)


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


def _is_zero_capacity(value: Any) -> bool:
    """Return True if the capacity value is numerically zero."""
    if value is None:
        return False
    # Pint quantities expose ``magnitude``.
    magnitude = getattr(value, "magnitude", value)
    try:
        return math.isclose(float(magnitude), 0.0, abs_tol=1e-08)
    except (TypeError, ValueError):
        return False


def _resolve_coupling_coefficient(flex_model: dict) -> float:
    """Resolve a coupled device's internal signed coupling coefficient.

    Coupling coefficients in flex-models are user-facing positive magnitudes.
    The internal sign is inferred from which directional capacity allows flow
    (mirroring how a missing directional site/device capacity defaults to zero):

    - only a (non-zero) ``consumption_capacity`` flows -> input device ->
      internally positive coefficient
    - only a (non-zero) ``production_capacity`` flows -> output device ->
      internally negative coefficient

    The unspecified direction is assumed to be zero, so the user no longer needs
    to set the opposite direction to a fixed 0 (though doing so still works).
    """
    coefficient = abs(float(flex_model.get("coupling_coefficient", 1.0)))
    consumption = flex_model.get("consumption_capacity")
    production = flex_model.get("production_capacity")
    consumption_flows = consumption is not None and not _is_zero_capacity(consumption)
    production_flows = production is not None and not _is_zero_capacity(production)
    consumption_blocked = _is_zero_capacity(consumption)
    production_blocked = _is_zero_capacity(production)
    # A direction is active if it flows itself, or if the opposite direction is
    # explicitly pinned to zero (the legacy way of marking a direction).
    consumption_active = consumption_flows or production_blocked
    production_active = production_flows or consumption_blocked
    if production_active and not consumption_active:
        # Output (producing) device -> internally negative coefficient.
        coefficient = -coefficient
    return coefficient


def _quantity_to_mw(value: Any) -> float | None:
    """Convert a fixed power quantity to a magnitude in MW; None if it is not a fixed scalar quantity.

    Sensor references and time series (used for time-varying capacities) return None:
    a unit-committed coupling group needs scalar bounds, so those are handled by the caller.
    """
    if value is None:
        return None
    if hasattr(value, "to") and hasattr(value, "magnitude"):
        try:
            return float(value.to("MW").magnitude)
        except Exception:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_coupling_base(base_value: Any, coefficient: float) -> float:
    """Resolve a coupled port's signed no-load base (in MW) from its raw ``coupling-base`` value.

    The ``coupling-base`` field is a user-facing positive power magnitude; its internal
    sign follows the port's flow direction, i.e. the sign of the port's coupling
    coefficient (mirroring :func:`_resolve_coupling_coefficient`). Returns 0.0 when no
    base is given (proportional, non-unit-committed behaviour).
    """
    magnitude = _quantity_to_mw(base_value)
    if magnitude is None:
        return 0.0
    return math.copysign(abs(magnitude), coefficient)


def _ref_id(value: Any) -> int | None:
    """Return the id of a sensor/asset reference, which may be a model object or a raw id."""
    if value is None:
        return None
    return value.id if hasattr(value, "id") else value


def resolve_group_key(flex_model: dict | None) -> tuple[str, int] | None:
    """Return a normalized ("sensor", id) or ("asset", id) key for the group a flex-model entry's "group" field references, or None if it has none."""
    if flex_model is None:
        return None
    group = flex_model.get("group")
    if not group:
        return None
    if isinstance(group, dict):
        group_sensor_id = _ref_id(group.get("sensor"))
        group_asset_id = _ref_id(group.get("asset"))
    else:
        # Backwards compatibility: a raw sensor id/object.
        group_sensor_id = _ref_id(group)
        group_asset_id = None
    if group_sensor_id is not None:
        return ("sensor", group_sensor_id)
    if group_asset_id is not None:
        return ("asset", group_asset_id)
    return None


def group_key_label(group_key: tuple[str, int]) -> str:
    """Return a human-readable label for a group key, for use in error messages."""
    kind, gid = group_key
    return f"{kind} {gid}"


def _match_own_group_key(
    flex_model: dict, referenced_group_keys: set[tuple[str, int]]
) -> tuple[str, int] | None:
    """Return the group key under which this entry is referenced as a group, if any.

    An entry is a group entry when its own "sensor" matches the sensor referenced by
    another entry's "group" field, or when its own "asset" matches the asset referenced
    by another entry's "group" field.

    :raises ValueError: When an asset-referenced group entry also carries a "sensor" field.
    """
    own_sensor_id = _ref_id(flex_model.get("sensor"))
    if own_sensor_id is not None and ("sensor", own_sensor_id) in referenced_group_keys:
        return ("sensor", own_sensor_id)
    own_asset_id = _ref_id(flex_model.get("asset"))
    if own_asset_id is not None and ("asset", own_asset_id) in referenced_group_keys:
        if own_sensor_id is not None:
            raise ValueError(
                f"Group entry for asset {own_asset_id} is referenced by asset,"
                " but also carries a 'sensor' field;"
                " an asset-referenced group entry must not define its own power sensor."
            )
        return ("asset", own_asset_id)
    return None


def _collect_referenced_group_keys(
    flex_model_list: list[dict], is_single_sensor_mode: bool
) -> set[tuple[str, int]]:
    """Collect the group keys referenced by entries' "group" fields.

    :raises ValueError: When a single-sensor flex-model carries a "group" field
                        (groups are only supported in multi-device mode).
    """
    if is_single_sensor_mode:
        if any(isinstance(fm, dict) and fm.get("group") for fm in flex_model_list):
            raise ValueError(
                "The 'group' field is only supported in multi-device flex-models."
            )
        return set()
    referenced_group_keys: set[tuple[str, int]] = set()
    for fm in flex_model_list:
        group_key = resolve_group_key(fm)
        if group_key is not None:
            referenced_group_keys.add(group_key)
    return referenced_group_keys


def _classify_group_entry(inventory: DeviceInventory, fm: dict) -> bool:
    """Classify a flex-model entry as a group entry, if its own sensor/asset is referenced as a group.

    Group entries are not schedulable devices;
    they carry constraints on the summed power of their member devices,
    so they must be classified before their power sensor or output sensors could make them pass for devices.

    :returns: True if the entry was classified (and registered) as a group entry.
    """
    if inventory.is_single_sensor_mode:
        return False
    own_group_key = _match_own_group_key(fm, inventory.referenced_group_keys)
    if own_group_key is None:
        return False
    own_sensor = fm.get("sensor")
    entry = FlexDevice(
        role=DeviceRole.GROUP,
        index=None,
        flex_model=fm,
        power_sensor=own_sensor if isinstance(own_sensor, Sensor) else None,
        asset=(own_sensor.asset if isinstance(own_sensor, Sensor) else fm.get("asset")),
    )
    inventory.entries.append(entry)
    inventory.group_entries[own_group_key] = fm
    return True


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
    #: Group entries (raw flex-model dicts) per group key: ("sensor", id) or ("asset", id).
    group_entries: dict[tuple[str, int], dict] = field(default_factory=dict)
    #: The group keys referenced by entries' "group" fields (used to detect dangling references).
    referenced_group_keys: set[tuple[str, int]] = field(default_factory=set)
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

        # Collect the group keys referenced by entries' "group" fields;
        # the entries whose own sensor/asset matches a referenced key are classified as group entries below.
        inventory.referenced_group_keys = _collect_referenced_group_keys(
            flex_model_list, is_single_sensor_mode
        )

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
            # Each flex-model entry is a deserialized dict.
            assert isinstance(fm, dict)
            # Group entry (multi-device mode only): this entry's own sensor/asset is
            # the aggregate sensor/asset referenced by another entry's "group" field.
            if _classify_group_entry(inventory, fm):
                continue

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
                coupling=fm.get("coupling"),
                coupling_coefficient=(
                    coupling_coefficient := _resolve_coupling_coefficient(fm)
                ),
                coupling_base=_resolve_coupling_base(
                    fm.get("coupling_base"), coupling_coefficient
                ),
                coupling_min=_quantity_to_mw(fm.get("coupling_min")),
                coupling_max=_quantity_to_mw(fm.get("power_capacity_in_mw")),
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

    def stock_constraint_device(self, stock_key: int) -> int | None:
        """Return the device that applies the given stock's SoC constraints.

        Hard SoC constraints (and the device-indexed remains of softened ones) land on
        the first device of the stock group, whose stock represents the group's stock
        in the solver. Use :attr:`stock_groups` to look up all member devices instead.
        """
        group_devices = self.stock_groups.get(stock_key)
        return group_devices[0] if group_devices else None

    @cached_property
    def coupling_groups(self) -> dict[str, list[tuple[int, float]]]:
        """Map each coupling-group name to its ports' (device index, signed coefficient) pairs.

        Devices sharing a coupling name are the commodity ports of one converter (e.g. a CHP unit's gas input, heat output and electricity output).
        The optimization model introduces a decision variable ``alpha`` per group per time step,
        and constrains every port by ``P[d] == coeff_d * alpha``.
        The coefficient signs follow the internal convention (see :func:`_resolve_coupling_coefficient`):
        positive for inputs, negative for outputs.
        The result is suitable for passing to ``device_scheduler(coupling_groups=...)``;
        it is empty when no device defines a ``coupling`` field.
        """
        groups: dict[str, list[tuple[int, float]]] = {}
        for device in self.devices:
            if device.coupling is None:
                continue
            groups.setdefault(device.coupling, []).append(
                (device.index, device.coupling_coefficient)
            )
        return groups

    def _coupling_reference_port(self, members: list[tuple[int, float]]) -> FlexDevice:
        """Return a coupling group's reference port: the port with |coefficient| == 1.

        The reference port is the driving variable of the group; it carries the group's
        ``coupling-min`` and the ``power-capacity`` that bounds the group's marginal level.

        :raises ValueError: When no member has a unit coefficient.
        """
        for d_idx, coeff in members:
            if math.isclose(abs(coeff), 1.0, abs_tol=1e-9):
                return self.devices[d_idx]
        raise ValueError(
            "A unit-committed coupling group must have a reference port with"
            " coupling-coefficient 1 (the driving variable). None was found."
        )

    @cached_property
    def coupling_uc(self) -> dict[str, tuple[float, float]]:
        """Map each unit-committed coupling group to its ``(min, max)`` marginal-level bounds (in MW).

        A coupling group is unit-committed when its reference port declares a
        ``coupling-min``, or any of its ports declares a non-zero ``coupling-base``.
        The minimum comes from the reference port's ``coupling-min`` (0 when only a base
        is given); the maximum from the reference port's ``power-capacity``.
        Empty for purely proportional coupling (leaving the problem an LP).

        :raises ValueError: When a unit-committed group lacks a resolvable power-capacity
                            on its reference port.
        """
        result: dict[str, tuple[float, float]] = {}
        for name, members in self.coupling_groups.items():
            group_devices = [self.devices[d_idx] for d_idx, _ in members]
            declared_mins = [
                dev.coupling_min
                for dev in group_devices
                if dev.coupling_min is not None
            ]
            has_base = any(abs(dev.coupling_base) > 1e-12 for dev in group_devices)
            if not declared_mins and not has_base:
                continue
            reference = self._coupling_reference_port(members)
            min_level = declared_mins[0] if declared_mins else 0.0
            max_level = reference.coupling_max
            if max_level is None:
                raise ValueError(
                    f"Unit-committed coupling group '{name}' needs a fixed power-capacity"
                    " on its reference port (the port with coupling-coefficient 1) to bound"
                    " its marginal level."
                )
            result[name] = (min_level, max_level)
        return result

    @cached_property
    def coupling_bases(self) -> dict[str, list[tuple[int, float]]]:
        """Map each unit-committed coupling group to its ports' (device index, signed base) pairs (in MW).

        Restricted to the groups in :attr:`coupling_uc`; suitable for passing to
        ``device_scheduler(coupling_bases=...)`` alongside ``coupling_groups``.
        """
        uc_groups = self.coupling_uc
        result: dict[str, list[tuple[int, float]]] = {}
        for name, members in self.coupling_groups.items():
            if name not in uc_groups:
                continue
            result[name] = [
                (d_idx, self.devices[d_idx].coupling_base) for d_idx, _ in members
            ]
        return result

    @cached_property
    def group_to_devices(self) -> dict[tuple[str, int], list[int]]:
        """Map each group key to the indices of the (leaf) member devices of that group.

        Membership is resolved transitively:
        a group entry may itself belong to another group (via its own "group" field),
        in which case its member devices count as members of the outer group, too.

        :raises ValueError: When group entries reference each other cyclically.
        """
        resolved: dict[tuple[str, int], list[int]] = {}

        def resolve_leaf_devices(
            group_key: tuple[str, int], path: tuple[tuple[str, int], ...] = ()
        ) -> list[int]:
            if group_key in path:
                raise ValueError(
                    f"Cyclic 'group' reference detected involving group "
                    f"{group_key_label(group_key)}."
                )
            if group_key in resolved:
                return resolved[group_key]
            leaves: list[int] = []
            seen: set[int] = set()
            for device in self.devices:
                if device.group_key == group_key and device.index not in seen:
                    leaves.append(device.index)
                    seen.add(device.index)
            # Also resolve members that are themselves groups pointing at this group.
            for other_key, other_entry in self.group_entries.items():
                if other_key == group_key:
                    continue
                if resolve_group_key(other_entry) == group_key:
                    for leaf in resolve_leaf_devices(other_key, path + (group_key,)):
                        if leaf not in seen:
                            leaves.append(leaf)
                            seen.add(leaf)
            resolved[group_key] = leaves
            return leaves

        for group_key in self.group_entries:
            resolve_leaf_devices(group_key)
        return resolved

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
