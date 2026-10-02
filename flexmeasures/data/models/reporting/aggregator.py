from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pint
import timely_beliefs as tb
from flask import current_app

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.planning.devices import (
    resolve_group_reference,
    group_key_label,
)
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.reporting.aggregation import (
    AggregatorConfigSchema,
    AggregatorParametersSchema,
)

from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import convert_units, is_energy_unit


class GroupMember:
    """One device of a group, as the flex-config describes it.

    Only what aggregating needs is read off the entry: the sensor recording the device,
    whether positive values on it mean consumption, and the asset it sits on, so that members can be filtered by type.
    """

    def __init__(
        self,
        sensor: Sensor,
        asset: GenericAsset,
        consumption_is_positive: bool | None,
    ) -> None:
        self.sensor = sensor
        self.asset = asset
        self.consumption_is_positive = consumption_is_positive


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

    # ------------------------------------------------------------------ groups

    def _group_root_asset(self) -> GenericAsset:
        """Return the asset whose subtree holds the group and its members.

        A group referenced by asset is that asset; one referenced by sensor is the asset the sensor sits on.
        Members are looked for in that asset's subtree, which is where the equipment a group stands for puts them.
        """
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
        return sensor.generic_asset

    def _group_members(self) -> list[GroupMember]:
        """Resolve the members of the configured group from the flex-models in its subtree.

        Membership is read from the same `group` field, through the same resolver, that the scheduler reads it from,
        so that adding a device to a group adds it to this report as well, with nothing to keep in sync.
        """
        group_key = resolve_group_reference(self._config["group"])
        root = self._group_root_asset()
        if root is None:
            raise ValueError(
                "The AggregatorReporter cannot find the asset of the group it was asked to aggregate."
            )

        members: list[GroupMember] = []
        for asset_id, entry in root.get_flex_model().items():
            if resolve_group_reference(entry.get("group")) != group_key:
                continue
            member_asset = self._asset(asset_id)
            for field, consumption_is_positive in (
                ("inflexible-consumption", True),
                ("inflexible-production", False),
                ("consumption", True),
                ("production", False),
            ):
                sensor = self._referenced_sensor(entry.get(field))
                if sensor is not None:
                    members.append(
                        GroupMember(sensor, member_asset, consumption_is_positive)
                    )
                    break
            else:
                sensor = self._referenced_sensor(entry.get("sensor"))
                if sensor is not None:
                    # a plain power sensor follows the platform convention unless the sensor says otherwise
                    members.append(
                        GroupMember(
                            sensor,
                            member_asset,
                            not sensor.get_attribute("consumption_is_positive", True)
                            is False,
                        )
                    )

        members = self._filter_members(members)
        return sorted(members, key=lambda member: member.sensor.id)

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
        root = self._group_root_asset()
        if root is None:
            return None
        for asset_id, entry in root.get_flex_model().items():
            if group_key == ("asset", asset_id):
                return entry
            own_sensor = self._referenced_sensor(entry.get("sensor"))
            if own_sensor is not None and group_key == ("sensor", own_sensor.id):
                return entry
        return None

    @staticmethod
    def _asset(asset_id: int) -> GenericAsset | None:
        from flexmeasures.data import db

        return db.session.get(GenericAsset, asset_id)

    @staticmethod
    def _referenced_sensor(reference: Any) -> Sensor | None:
        """Resolve a serialized sensor reference, which may be an id, a `{"sensor": id}` dict, or a Sensor."""
        from flexmeasures.data import db

        if reference is None:
            return None
        if isinstance(reference, Sensor):
            return reference
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
        """Return whether positive values on the output sensor mean consumption.

        The group's own entry decides: an aggregate recorded under `production` is production-positive,
        one recorded under `consumption` is consumption-positive.
        """
        entry = self._group_entry() or {}
        if self._referenced_sensor(entry.get("production")) is not None:
            return False
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
                # a member whose sign convention differs from the aggregate's is negated
                if (
                    member.consumption_is_positive is not None
                    and member.consumption_is_positive != group_is_consumption_positive
                ):
                    description["_sign"] = -1.0
                input_descriptions.append(description)

        return input_descriptions

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
            return resampler.sum() if is_stock else resampler.mean()

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
        upsampled = extended.resample(resolution).ffill().iloc[:-1]
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

        output = self._resolve_output(output or [])
        output_sensor: Sensor = output[0]["sensor"]

        if resolution is None:
            resolution = output_sensor.event_resolution

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

        for index, input_description in enumerate(input_descriptions):
            sensor: Sensor = input_description.pop("sensor")
            column_name = input_description.pop("name", f"sensor_{sensor.id}")
            sign = input_description.pop("_sign", 1.0)

            source = input_description.pop(
                "source", input_description.pop("sources", None)
            )
            if source is not None and not isinstance(source, list):
                source = [source]

            df = sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                beliefs_before=belief_time,
                horizons_at_most=belief_horizon,
                source=source,
                one_deterministic_belief_per_event=True,
                **input_description,
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

        aggregated = pd.concat(columns, axis=1).aggregate(method, axis=1)

        # Built explicitly, because resampling the inputs with pandas leaves plain Series behind,
        # and the report has to come back as a BeliefsDataFrame of the output sensor.
        flat = pd.DataFrame(
            {
                "event_start": aggregated.index,
                "event_value": aggregated.to_numpy(),
                "source": self.data_source,
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
