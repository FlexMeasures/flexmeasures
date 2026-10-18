from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pint
import timely_beliefs as tb
from flask import current_app
from marshmallow import ValidationError

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.planning.devices import (
    resolve_group_reference,
    group_key_label,
)
from flexmeasures.data.models.reporting import Reporter, read_input_beliefs
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.reporting.aggregation import (
    AggregatorConfigSchema,
    AggregatorParametersSchema,
)

from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import convert_units, is_energy_unit


class GroupMember:
    """One reading of one device of a group, as the flex-config describes it.

    A device that records its consumption and its production on two sensors contributes two of these.
    `source_filters` carries the provenance the flex-config states for the device, so that a report reads
    the same beliefs the scheduler would.
    """

    def __init__(
        self,
        sensor: Sensor,
        asset: GenericAsset | None,
        consumption_is_positive: bool,
        source_filters: dict[str, Any] | None = None,
    ) -> None:
        self.sensor = sensor
        self.asset = asset
        self.consumption_is_positive = consumption_is_positive
        self.source_filters = source_filters or {}


def _sensor_is_consumption_positive(sensor: Sensor) -> bool:
    """Return whether positive values on a sensor mean consumption.

    The platform's default is production-positive, as `_resolve_schedule_output_sign` and the profit reporter also read it.
    """
    return bool(sensor.get_attribute("consumption_is_positive", False))


def _source_filters_of(reference: Any) -> dict[str, Any]:
    """Return the belief-search filters a flex-config sensor reference states, if any.

    The flex-config's provenance belongs to the topology, so a member's filters are inherited rather than restated in the report.
    """
    if reference is None:
        return {}
    filters: dict[str, Any] = {}
    if getattr(reference, "sources", None):
        filters["sources"] = list(reference.sources)
    if getattr(reference, "source_types", None):
        filters["source_types"] = list(reference.source_types)
    if getattr(reference, "exclude_source_types", None):
        filters["exclude_source_types"] = list(reference.exclude_source_types)
    if getattr(reference, "source_account", None):
        filters["source_account_ids"] = [
            account.id for account in reference.source_account
        ]
    return filters


class AggregatorReporter(Reporter):
    """Aggregate the sensors of a device group, or sensors named one by one.

    A site's flex-config already describes its topology: which devices sit behind which piece of equipment (their `group`),
    which sensor records each of them, which sign means consumption or production, and which sensor a group's aggregate belongs on.
    Naming a `group` reports the measured aggregate of that group, so the report needs no topology of its own and cannot drift from the one the scheduler uses.
    A `members` filter narrows a group down to a category of its devices, such as every PV installation behind a connection.

    Sensors can still be named one by one as `input` parameters, which is the way to aggregate something other than a site's power,
    or to subtract one sensor's data from another's using `weights`.

    Values are converted to the unit of the output sensor at each sensor's own resolution, before being resampled to the output's resolution,
    because converting between a stock and a flow (kWh to MW, say) depends on the resolution of the data being converted.
    """

    __version__ = "2"
    __author__ = "Seita"

    _config_schema = AggregatorConfigSchema()
    _parameters_schema = AggregatorParametersSchema()

    weights: dict
    method: str

    #: The site's classified flex-config, built once per reporter and reused.
    _cached_inventory: Any = None
    #: The report's window, used only so the inventory is built the way a scheduler of this site would build it.
    _window_start: datetime | None = None
    _window_end: datetime | None = None

    # ------------------------------------------------------------------ groups

    def _group_asset(self) -> GenericAsset | None:
        """Return the asset (or the asset of the sensor) the configured group refers to."""
        from flexmeasures.data import db

        group = self._config["group"]
        asset = group.get("asset")
        if asset is not None:
            return (
                asset
                if isinstance(asset, GenericAsset)
                else db.session.get(GenericAsset, asset)
            )
        sensor = group.get("sensor")
        sensor = (
            sensor if isinstance(sensor, Sensor) else db.session.get(Sensor, sensor)
        )
        return sensor.generic_asset if sensor is not None else None

    def _site_root(self) -> GenericAsset:
        """Return the top-level ancestor of the group's asset.

        A device may join a group from anywhere below the site, so the flex-config has to be gathered
        from the site root, which is the asset a scheduler of this site would be given.
        """
        asset = self._group_asset()
        if asset is None:
            raise ValueError(
                "The AggregatorReporter cannot find the asset of the group it was asked to aggregate."
            )
        while asset.parent_asset is not None:
            asset = asset.parent_asset
        return asset

    def _inventory(self):
        """Classify the site's flex-config the way a scheduler of that site would.

        Going through the scheduler's own device inventory is what keeps one description of the site:
        it resolves a group to its leaf devices, follows groups nested inside groups,
        finds members wherever they sit below the site, and classifies each device's role and sign convention.
        The window does not affect membership, so a nominal one is enough when the report has not named one yet.
        The result is cached, because building it costs a query per asset.
        """
        if self._cached_inventory is not None:
            return self._cached_inventory

        from flexmeasures.data.models.planning.storage import StorageScheduler

        root = self._site_root()
        start = self._window_start or server_now()
        end = self._window_end or (start + timedelta(hours=1))
        scheduler = StorageScheduler(
            asset_or_sensor=root,
            start=start,
            end=end,
            resolution=root.sensors[0].event_resolution if root.sensors else None,
        )
        try:
            scheduler.deserialize_config()
        except (ValidationError, ValueError) as e:
            raise ValueError(
                f"The report could not read the flex-config of site {root.id} ({root.name}),"
                f" which it needs to resolve the group's members."
                f"{self._name_invalid_entry(root, start, end)}"
                f" A scheduler of this site would fail on it too. The flex-config says: {e}"
            )
        self._cached_inventory = scheduler.device_inventory
        return self._cached_inventory

    def _name_invalid_entry(self, root: GenericAsset, start, end) -> str:
        """Return a phrase naming the asset whose flex-model entry the site's flex-config fails on, if one can be pinned down.

        Only reached once the site's flex-config has already failed, so the cost of probing each asset's own entry is paid
        on the way to an error message rather than on every report.
        """
        from flexmeasures.data.models.planning.storage import StorageScheduler

        failing = []
        for asset_id in root.get_flex_model():
            asset = self._asset_by_id(asset_id)
            if asset is None:
                continue
            try:
                StorageScheduler(
                    asset_or_sensor=asset, start=start, end=end
                ).deserialize_config()
            except (ValidationError, ValueError):
                failing.append(asset)

        # A scheduler on an asset reads its subtree's flex-model as well, so an asset whose descendant is at fault
        # fails along with it. Only the deepest assets that fail are named.
        offenders = [
            f"{asset.id} ({asset.name})"
            for asset in failing
            if not any(
                other is not asset and self._is_ancestor_of(asset, other)
                for other in failing
            )
        ]
        if not offenders:
            return ""
        if len(offenders) == 1:
            return (
                f" The entry on asset {offenders[0]} is the one that does not validate."
            )
        return f" The entries on assets {', '.join(offenders)} do not validate."

    @staticmethod
    def _is_ancestor_of(asset: GenericAsset, other: GenericAsset) -> bool:
        """Tell whether `asset` sits above `other` in the asset tree."""
        parent = other.parent_asset
        while parent is not None:
            if parent.id == asset.id:
                return True
            parent = parent.parent_asset
        return False

    @staticmethod
    def _asset_by_id(asset_id: int) -> GenericAsset | None:
        from flexmeasures.data import db

        return db.session.get(GenericAsset, asset_id)

    def _group_members(self) -> list[GroupMember]:
        """Resolve the readings that make up the configured group's aggregate.

        Membership comes from the scheduler's device inventory, so adding a device to a group adds it to this report,
        and a group of groups is resolved to the devices behind it rather than to the inner groups' own output sensors.
        """
        group_key = resolve_group_reference(self._config["group"])
        inventory = self._inventory()
        group_to_devices = inventory.group_to_devices

        if group_key not in group_to_devices:
            raise ValueError(
                f"Nothing in the flex-config of this site joins the group {group_key_label(group_key) if group_key else 'that was configured'}."
                " A device joins a group through the `group` field of its flex-model entry, which is also what makes the group count for scheduling."
            )

        by_index = {
            device.index: device
            for device in (*inventory.devices, *inventory.inflexible_devices)
            if device.index is not None
        }

        members: list[GroupMember] = []
        for index in group_to_devices[group_key]:
            device = by_index.get(index)
            if device is not None:
                members.extend(self._member_readings(device))

        members = self._filter_members(members)
        return sorted(members, key=lambda member: member.sensor.id)

    @staticmethod
    def _member_readings(device) -> list[GroupMember]:
        """Return the readings of one member device: one per sensor its measurements are on.

        A device that names its own power sensor is read from that sensor, because that is where its measurements are.
        Its `consumption` and `production` references are where a schedule is written, so reading those instead would
        leave a realized report with nothing for this device.
        An entry that names no power sensor of its own records its two directions separately,
        and then contributes both, each with the sign convention of the field it was named under.
        """
        source_filters = _source_filters_of(device.sensor_reference)

        def reading(sensor, consumption_is_positive) -> GroupMember:
            if consumption_is_positive is None:
                consumption_is_positive = _sensor_is_consumption_positive(sensor)
            return GroupMember(
                sensor, device.asset, consumption_is_positive, source_filters
            )

        own_sensor = AggregatorReporter._referenced_sensor(
            (device.flex_model or {}).get("sensor")
        )
        if own_sensor is not None:
            return [reading(own_sensor, device.consumption_is_positive)]

        readings = [
            reading(sensor, consumption_is_positive)
            for sensor, consumption_is_positive in (
                (device.consumption_sensor, True),
                (device.production_sensor, False),
            )
            if sensor is not None
        ]
        if readings:
            return readings

        if device.power_sensor is None:
            return []
        return [reading(device.power_sensor, device.consumption_is_positive)]

    def _filter_members(self, members: list[GroupMember]) -> list[GroupMember]:
        """Narrow the group's members down with the `members` filter, if one is configured."""
        member_filter = self._config.get("members") or {}
        asset_type = member_filter.get("asset_type")
        if not asset_type:
            return members
        return [
            member
            for member in members
            if member.asset is not None
            and member.asset.generic_asset_type is not None
            and member.asset.generic_asset_type.name == asset_type
        ]

    def _group_entry(self) -> dict | None:
        """Return the flex-model entry of the group itself, which says where its aggregate is recorded."""
        group_key = resolve_group_reference(self._config["group"])
        return self._inventory().group_entries.get(group_key)

    @staticmethod
    def _referenced_sensor(reference: Any) -> Sensor | None:
        """Resolve a sensor reference, which may be a Sensor, a SensorReference, an id, or a `{"sensor": ...}` dict."""
        from flexmeasures.data import db

        if reference is None:
            return None
        if isinstance(reference, Sensor):
            return reference
        if isinstance(getattr(reference, "sensor", None), Sensor):
            return reference.sensor
        if isinstance(reference, dict):
            return AggregatorReporter._referenced_sensor(reference.get("sensor"))
        if isinstance(reference, bool):
            return None
        if isinstance(reference, int):
            return db.session.get(Sensor, reference)
        if isinstance(reference, str) and reference.isdigit():
            return db.session.get(Sensor, int(reference))
        return None

    # ----------------------------------------------------------- sensor lists

    @property
    def input_sensors(self) -> list:
        """Return the sensors read by this reporter, including the members of a configured group."""
        if not self._config.get("group"):
            return self._resolve_sensors(super().input_sensors)
        output_sensor_ids = {sensor.id for sensor in self.output_sensors}
        member_sensors = [
            member.sensor
            for member in self._group_members()
            if member.sensor.id not in output_sensor_ids
        ]
        return self._resolve_sensors(super().input_sensors, member_sensors)

    @property
    def output_sensors(self) -> list:
        """Return the sensor this reporter records on, which a group takes from its own flex-model entry."""
        parameters = self._parameters or {}
        named = parameters.get("output") or []
        if named:
            return self._resolve_sensors([item.get("sensor") for item in named])
        if not self._config.get("group"):
            return []
        sensor = self._group_output_sensor(raise_if_missing=False)
        return self._resolve_sensors([sensor])

    def _group_output_sensor(self, raise_if_missing: bool = True) -> Sensor | None:
        """Return the sensor the group's aggregate is recorded on.

        A group referenced by sensor records on that sensor.
        A group referenced by asset records on the `production` or `consumption` output sensor its own entry names.
        """
        group_key = resolve_group_reference(self._config["group"])
        if group_key is not None and group_key[0] == "sensor":
            sensor = self._referenced_sensor(group_key[1])
            if sensor is not None:
                return sensor

        entry = self._group_entry()
        if entry is not None:
            for field in ("production", "consumption"):
                sensor = self._referenced_sensor(entry.get(field))
                if sensor is not None:
                    return sensor

        if not raise_if_missing:
            return None
        raise ValueError(
            f"The group ({group_key_label(group_key) if group_key else 'unknown'}) does not say where its aggregate is recorded."
            " Give its flex-model entry a `production` or `consumption` output sensor, or name an output sensor in the `output` parameters."
        )

    def _group_sign(self) -> bool:
        """Return whether positive values on the sensor the aggregate is recorded on mean consumption.

        A group referenced by asset says so through the field its own entry records under:
        an aggregate under `production` is production-positive, one under `consumption` is consumption-positive.
        A group referenced by a sensor has no such field, so that sensor's own convention decides,
        which is production-positive unless the sensor says otherwise.
        """
        group_key = resolve_group_reference(self._config["group"])
        entry = self._group_entry() or {}
        if self._referenced_sensor(entry.get("production")) is not None:
            return False
        if self._referenced_sensor(entry.get("consumption")) is not None:
            return True
        if group_key is not None and group_key[0] == "sensor":
            sensor = self._referenced_sensor(group_key[1])
            if sensor is not None:
                return _sensor_is_consumption_positive(sensor)
        return True

    # ------------------------------------------------------------------ input

    def _collect_input_descriptions(
        self, input: list[dict[str, Any]], output_sensor: Sensor
    ) -> list[dict[str, Any]]:
        """List what to read, combining the `input` parameters with the members of a configured group.

        The input descriptions are copied, so that reading them does not consume the parameters the reporter was given.
        The output sensor is never aggregated into itself, which would fold each run's own result into the next one.
        """
        input_descriptions = [dict(input_description) for input_description in input]
        described_sensor_ids = {
            input_description["sensor"].id for input_description in input_descriptions
        }

        if self._config.get("group"):
            group_is_consumption_positive = self._group_sign()
            for member in self._group_members():
                if member.sensor.id == output_sensor.id:
                    continue
                if member.sensor.id in described_sensor_ids:
                    continue
                described_sensor_ids.add(member.sensor.id)
                description: dict[str, Any] = {"sensor": member.sensor}
                # the provenance the flex-config states for this member is inherited, not restated in the report
                description.update(member.source_filters)
                # a member whose sign convention differs from the aggregate's is negated
                if member.consumption_is_positive != group_is_consumption_positive:
                    description["_sign"] = -1.0
                input_descriptions.append(description)

        return input_descriptions

    # --------------------------------------------------------- accountability

    def _record_membership(self, members: list[GroupMember]) -> None:
        """Record which sensors the group resolved to, as part of the report's data source.

        Membership comes from the flex-config, so the set of aggregated devices can change without the report's configuration changing.
        Recording the resolved membership on the data source traces each stored report to the devices it aggregated:
        adding a device to a group records the next report under a different source.
        Changes to the membership itself are noted in the group asset's audit log when they are made.
        """
        resolved = sorted(member.sensor.id for member in members)
        # which members were missing is filled in per event, so whatever was given here describes no event yet
        given_missing = self._config.pop("missing_members", None)
        if self._config.get("resolved_members") == resolved and given_missing is None:
            return
        self._config["resolved_members"] = resolved
        # the membership is part of the source's identity, so the cached source no longer describes this run
        self._data_source = None

    def _label_incomplete_events(
        self,
        frame: pd.DataFrame,
        incomplete: pd.Series,
        column_sensor_ids: dict[str, int],
        sources: pd.Series,
    ) -> pd.Series:
        """Record each event that some sensors did not report under a source that names them, in its `missing-members`.

        The complete aggregate keeps its own source, which says nothing about missing members,
        so a consumer can tell a partial aggregate from a complete one, and an aggregate recorded once its data is complete supersedes the partial one.
        Which sensors are missing can differ per event, so one report may record under several sources.
        A sensor that fails again later is recorded under the source it was recorded under before, as sources with the same attributes are shared.
        """
        missing = frame.loc[incomplete].isna()
        events_by_missing_set: dict[tuple[int, ...], list] = {}
        for event_start, row in missing.iterrows():
            missing_ids = tuple(
                sorted({column_sensor_ids[column] for column in row.index[row]})
            )
            events_by_missing_set.setdefault(missing_ids, []).append(event_start)

        complete_source = self.data_source
        sources = sources.copy()
        try:
            for missing_ids, event_starts in events_by_missing_set.items():
                self._config["missing_members"] = list(missing_ids)
                self._data_source = None
                sources.loc[event_starts] = self.data_source
        finally:
            self._config.pop("missing_members", None)
            self._data_source = complete_source
        return sources

    # ------------------------------------------------------------------ units

    def _to_output_unit(
        self, values: pd.Series, sensor: Sensor, output_sensor: Sensor
    ) -> pd.Series:
        """Convert one sensor's values to the unit of the output sensor, at the sensor's own resolution.

        The resolution matters: converting between a stock and a flow (kWh to MW, say) divides by the duration of an event,
        so this has to happen before the values are resampled to the output's resolution.
        """
        if sensor.unit == output_sensor.unit:
            return values

        if sensor.unit == "" or output_sensor.unit == "":
            # An empty unit carries nothing to convert by, so the values are left as they are.
            # This keeps reports on sensors that never had a unit working; set a unit on both sensors to have them reconciled.
            current_app.logger.warning(
                f"Not converting the values of sensor {sensor.id} ({sensor.name}) from '{sensor.unit}' to '{output_sensor.unit}', because one of these units is empty."
                f" Set a unit on both sensors so that the aggregate is expressed in a known unit."
            )
            return values

        try:
            return convert_units(
                values,
                from_unit=sensor.unit,
                to_unit=output_sensor.unit,
                event_resolution=sensor.event_resolution,
            )
        except (pint.errors.PintError, ValueError) as e:
            raise ValueError(
                f"Cannot aggregate sensor {sensor.id} ({sensor.name}), which records in '{sensor.unit}',"
                f" onto sensor {output_sensor.id} ({output_sensor.name}), which records in '{output_sensor.unit}': {e}"
                f" Aggregate sensors that record a comparable quantity, or convert with an explicit weight."
            )

    @staticmethod
    def _resample(
        values: pd.Series,
        resolution: timedelta,
        sensor_resolution: timedelta,
        unit: str,
    ) -> pd.Series:
        """Resample one sensor's converted values to the resolution the report is recorded at.

        Whether a quantity adds up or averages over a longer event depends on what it is:
        energy adds up, power averages, so the unit of the output sensor decides which.
        Going the other way, to a finer resolution, a power holds through the event it was recorded over, while an energy is divided over it.
        """
        if values.empty or resolution == sensor_resolution:
            return values

        is_stock = is_energy_unit(unit)

        if resolution > sensor_resolution:
            resampler = values.resample(resolution)
            # min_count keeps an event with no data missing, rather than reporting it as zero energy
            return resampler.sum(min_count=1) if is_stock else resampler.mean()

        # A finer resolution than the sensor records at: carry each value across its own event.
        # The series is extended by one sensor event first, because resampling stops at the last index value,
        # which would otherwise leave the last event's tail empty.
        extended = pd.concat(
            [
                values,
                pd.Series(
                    [values.iloc[-1]], index=[values.index[-1] + sensor_resolution]
                ),
            ]
        )
        # The fill is limited to one of the sensor's own events, so a gap in the data stays a gap
        # instead of being filled with the last value before it.
        fill_limit = max(int(sensor_resolution / resolution) - 1, 0)
        upsampled = extended.resample(resolution).ffill(limit=fill_limit).iloc[:-1]
        if is_stock:
            upsampled = upsampled * (resolution / sensor_resolution)
        return upsampled

    # ----------------------------------------------------------------- report

    def _compute_report(
        self,
        start: datetime,
        end: datetime,
        output: list[dict[str, Any]] | None = None,
        input: list[dict[str, Any]] | None = None,
        resolution: timedelta | None = None,
        belief_time: datetime | None = None,
        belief_horizon: timedelta | None = None,
    ) -> list[dict[str, Any]]:
        """Read every sensor, express it in the output sensor's unit and resolution, and aggregate."""

        method: str = self._config.get("method", "sum")
        weights: dict = self._config.get("weights", {})

        self._window_start, self._window_end = start, end

        output = self._resolve_output(output or [])
        output_sensor: Sensor = output[0]["sensor"]

        if resolution is None:
            resolution = output_sensor.event_resolution

        if self._config.get("group"):
            self._record_membership(self._group_members())

        input_descriptions = self._collect_input_descriptions(
            input or [], output_sensor=output_sensor
        )
        if len(input_descriptions) == 0:
            raise ValueError(
                "The AggregatorReporter has no sensors to aggregate."
                " Name them in the `input` parameters, or name a device group of the flex-config in the reporter's `group` config field."
            )

        if belief_time is None and belief_horizon is None:
            belief_time = server_now()

        columns = []
        column_sensor_ids: dict[str, int] = {}

        for index, input_description in enumerate(input_descriptions):
            sensor: Sensor = input_description.pop("sensor")
            column_name = input_description.pop("name", f"sensor_{sensor.id}")
            sign = input_description.pop("_sign", 1.0)

            source = input_description.pop(
                "source", input_description.pop("sources", None)
            )
            if source is not None and not isinstance(source, list):
                source = [source]

            df = read_input_beliefs(
                sensor,
                input_description,
                event_starts_after=start,
                event_ends_before=end,
                beliefs_before=belief_time,
                horizons_at_most=belief_horizon,
                source=source,
                one_deterministic_belief_per_event=True,
            )

            self._check_one_source_per_event(df, sensor, source, input_description)

            values = df.droplevel([1, 2, 3])["event_value"]
            values = self._to_output_unit(values, sensor, output_sensor)
            values = self._resample(
                values, resolution, sensor.event_resolution, output_sensor.unit
            )

            values = values * sign
            if column_name in weights:
                values = values * weights[column_name]

            # a unique name per column, so that two entries for the same sensor both survive the concat
            columns.append(values.rename(f"{column_name}_{index}"))
            column_sensor_ids[f"{column_name}_{index}"] = sensor.id

        frame = pd.concat(columns, axis=1)
        aggregated = frame.aggregate(method, axis=1)

        # An event no sensor reported is missing, whichever mode this is: Pandas sums an all-missing row to zero,
        # which would report an hour nothing was measured in as an hour nothing flowed in.
        nothing_reported = frame.isna().all(axis=1)
        aggregated = aggregated.where(~nothing_reported)
        incomplete = frame.isna().any(axis=1) & ~nothing_reported

        sources = pd.Series(self.data_source, index=aggregated.index, dtype=object)
        if self._config.get("skip_missing") is False:
            if incomplete.any():
                self._warn_about_gaps(frame, incomplete)
                aggregated = aggregated.where(~incomplete)
        elif self._config.get("group") and incomplete.any():
            # Where the members were resolved for the caller, the caller cannot see which of them went in,
            # so an event that some of them did not report is recorded under a source that names them.
            # Where the caller named the sensors itself, aggregating what reported is what these reports have always done.
            sources = self._label_incomplete_events(
                frame, incomplete, column_sensor_ids, sources
            )

        # Built explicitly, because resampling the inputs with pandas leaves plain Series behind,
        # and the report has to come back as a BeliefsDataFrame of the output sensor.
        flat = pd.DataFrame(
            {
                "event_start": aggregated.index,
                "event_value": aggregated.to_numpy(),
                "source": sources.to_numpy(),
                "cumulative_probability": 0.5,
            }
        )
        if belief_time is not None:
            flat["belief_time"] = belief_time
        else:
            flat["belief_horizon"] = belief_horizon

        output_df = tb.BeliefsDataFrame(flat, sensor=output_sensor)
        output_df.event_resolution = output_sensor.event_resolution

        return [
            {
                "name": "aggregate",
                "column": "event_value",
                "sensor": output_sensor,
                "data": output_df,
            }
        ]

    def _assign_sensors_and_source(
        self, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Assign each result its sensor, and keep the sources the report chose per event.

        A report over a group records an event that some members did not report under a source of its own,
        which assigning the report's own source to every event would undo.
        """
        for result in results:
            result["data"].sensor = result["sensor"]
        return results

    @staticmethod
    def _warn_about_gaps(frame: pd.DataFrame, incomplete: pd.Series) -> None:
        """Say which sensors left gaps, and how many events they cost, because a blank aggregate is otherwise hard to place."""
        gaps = {
            column: int(frame[column].isna().sum())
            for column in frame.columns
            if frame[column].isna().any()
        }
        current_app.logger.warning(
            f"{int(incomplete.sum())} event(s) are left out of the aggregate because not every sensor reported them."
            f" Sensors with gaps, and the number of events each is missing: {gaps}."
            f" Leave `skip-missing` unset to aggregate whatever reported instead."
        )

    def _resolve_output(self, output: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Settle which sensor the aggregate is recorded on.

        An output named in the parameters wins, so one report can be sent elsewhere.
        Otherwise a configured group's own entry says where its aggregate belongs.
        """
        if output:
            return output
        if not self._config.get("group"):
            raise ValueError(
                "The AggregatorReporter has no sensor to record its report on."
                " Name one in the `output` parameters, or name a device group whose entry says where its aggregate belongs."
            )
        return [{"sensor": self._group_output_sensor()}]

    @staticmethod
    def _check_one_source_per_event(
        df, sensor: Sensor, source, input_description: dict
    ) -> None:
        """Refuse data that holds several sources for one event, unless the caller narrowed the sources down.

        Different versions of one source are not several sources, and neither is data a source filter has already narrowed,
        which is why a filtered search is accepted here even when more than one source remains.
        """
        if len(df.lineage.events) != len(df):
            duplicate_events = df[df.index.get_level_values("event_start").duplicated()]
            raise ValueError(
                f"{len(duplicate_events)} event(s) are duplicate. First duplicate: {duplicate_events[0]}. Consider using (more) source filters."
            )

        narrowed = bool(source) or any(
            input_description.get(key)
            for key in (
                "source_types",
                "exclude_source_types",
                "source_account_ids",
                "user_source_ids",
            )
        )
        if narrowed:
            return

        unique_sources = df.lineage.sources
        properties = ["name", "type", "model"]
        if len(unique_sources) > 1 and not all(
            getattr(other, prop) == getattr(unique_sources[0], prop)
            for prop in properties
            for other in unique_sources
        ):
            raise ValueError(
                f"Missing attribute 'sources' for input sensor {sensor.id}: {sensor.name} (to identify one specific source)."
                f" The field `sources` is required when having data with multiple sources within the time window, to ensure only required data is used in the reporter."
                f" We found data from the following sources: {[other.id for other in unique_sources]}."
            )
