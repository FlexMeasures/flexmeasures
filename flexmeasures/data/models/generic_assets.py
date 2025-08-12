from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import json

from flask import current_app
from flask_security import current_user
import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.sql.expression import func, text
from sqlalchemy.ext.mutable import MutableDict, MutableList
from timely_beliefs import BeliefsDataFrame, utils as tb_utils

from flexmeasures.data import db
from flexmeasures.data.models.annotations import Annotation, to_annotation_frame
from flexmeasures.data.models.charts import chart_type_to_chart_specs
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.parsing_utils import parse_source_arg
from flexmeasures.data.models.user import User
from flexmeasures.data.queries.annotations import query_asset_annotations
from flexmeasures.data.services.timerange import get_timerange
from flexmeasures.auth.policy import (
    AuthModelMixin,
    EVERY_LOGGED_IN_USER,
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
)
from flexmeasures.utils import geo_utils
from flexmeasures.utils.coding_utils import flatten_unique
from flexmeasures.utils.time_utils import determine_minimum_resampling_resolution
from flexmeasures.utils.unit_utils import find_smallest_common_unit


class GenericAssetType(db.Model):
    """An asset type defines what type an asset belongs to.

    Examples of asset types: WeatherStation, Market, CP, EVSE, WindTurbine, SolarPanel, Building.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="", unique=True)
    description = db.Column(db.String(80), nullable=True, unique=False)

    def __repr__(self):
        return "<GenericAssetType %s: %r>" % (self.id, self.name)


class GenericAsset(db.Model, AuthModelMixin):
    """An asset is something that has economic value.

    Examples of tangible assets: a house, a ship, a weather station.
    Examples of intangible assets: a market, a country, a copyright.
    """

    __table_args__ = (
        db.CheckConstraint(
            "parent_asset_id != id", name="generic_asset_self_reference_ck"
        ),
        db.UniqueConstraint(
            "name",
            "parent_asset_id",
            name="generic_asset_name_parent_asset_id_key",
        ),
    )

    # No relationship
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), default="")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    attributes = db.Column(MutableDict.as_mutable(db.JSON), nullable=False, default={})
    sensors_to_show = db.Column(
        MutableList.as_mutable(db.JSON), nullable=False, default=[]
    )
    flex_context = db.Column(
        MutableDict.as_mutable(db.JSON), nullable=False, default={}
    )
    # One-to-many (or many-to-one?) relationships
    parent_asset_id = db.Column(
        db.Integer, db.ForeignKey("generic_asset.id", ondelete="CASCADE"), nullable=True
    )
    generic_asset_type_id = db.Column(
        db.Integer, db.ForeignKey("generic_asset_type.id"), nullable=False
    )

    child_assets = db.relationship(
        "GenericAsset",
        cascade="all",
        backref=db.backref("parent_asset", remote_side="GenericAsset.id"),
    )

    generic_asset_type = db.relationship(
        "GenericAssetType",
        foreign_keys=[generic_asset_type_id],
        backref=db.backref("generic_assets", lazy=True),
    )

    # Many-to-many relationships
    annotations = db.relationship(
        "Annotation",
        secondary="annotations_assets",
        backref=db.backref("assets", lazy="dynamic"),
    )

    def __acl__(self):
        """
        All logged-in users can read if the asset is public.
        For non-public assets, we allow reading to whoever can read the account,
        and editing for every user in the account.
        Deletion is left to account admins.
        """
        return {
            "create-children": [
                f"account:{self.account_id}",
                (
                    (
                        f"account:{self.owner.consultancy_account_id}",
                        f"role:{CONSULTANT_ROLE}",
                    )
                    if self.owner is not None
                    else ()
                ),
            ],
            "read": (
                self.owner.__acl__()["read"]
                if self.account_id is not None
                else EVERY_LOGGED_IN_USER
            ),
            "update": [
                f"account:{self.account_id}",
                (
                    (
                        f"account:{self.owner.consultancy_account_id}",
                        f"role:{CONSULTANT_ROLE}",
                    )
                    if self.owner is not None
                    else ()
                ),
            ],
            "delete": [
                (f"account:{self.account_id}", f"role:{ACCOUNT_ADMIN_ROLE}"),
                (
                    (
                        f"account:{self.owner.consultancy_account_id}",
                        f"role:{CONSULTANT_ROLE}",
                    )
                    if self.owner is not None
                    else ()
                ),
            ],
        }

    def __repr__(self):
        return "<GenericAsset %s: %r (%s)>" % (
            self.id,
            self.name,
            self.generic_asset_type.name,
        )

    def validate_sensors_to_show(
        self,
        suggest_default_sensors: bool = True,
    ) -> list[dict[str, str | None | "Sensor" | list["Sensor"]]]:  # noqa: F821
        """
        Validate and transform the 'sensors_to_show' attribute into the latest format for use in graph-making code.

        This function ensures that the 'sensors_to_show' attribute:
        1. Follows the latest format, even if the data in the database uses an older format.
        2. Contains only sensors that the user has access to (based on the current asset, account, or public availability).

        Steps:
        - The function deserializes the 'sensors_to_show' data from the database, ensuring that older formats are parsed correctly.
        - It checks if each sensor is accessible by the user and filters out any unauthorized sensors.
        - The sensor structure is rebuilt according to the latest format, which allows for grouping sensors and adding optional titles.

        Details on format:
        - The 'sensors_to_show' attribute is defined as a list of sensor IDs or nested lists of sensor IDs (to indicate grouping).
        - Titles may be associated with rows of sensors. If no title is provided, `{"title": None}` will be assigned.
        - Nested lists of sensors indicate that they should be shown together (e.g., layered in the same chart).

        Example inputs:
        1. Simple list of sensors, where sensors 42 and 44 are grouped:
            sensors_to_show = [40, 35, 41, [42, 44], 43, 45]

        2. List with titles and sensor groupings:
            sensors_to_show = [
                {"title": "Title 1", "sensor": 40},
                {"title": "Title 2", "sensors": [41, 42]},
                [43, 44], 45, 46
            ]

        Parameters:
        - suggest_default_sensors: If True, the function will suggest default sensors if 'sensors_to_show' is not set.
        - If False, the function will return an empty list if 'sensors_to_show' is not set.

        Returned structure:
        - The function returns a list of dictionaries, with each dictionary containing either a 'sensor' (for individual sensors) or 'sensors' (for groups of sensors), and an optional 'title'.
        - Example output:
            [
                {"title": "Title 1", "sensor": <Sensor object for sensor 40>},
                {"title": "Title 2", "sensors": [<Sensor object for sensor 41>, <Sensor object for sensor 42>]},
                {"title": None, "sensors": [<Sensor object for sensor 43>, <Sensor object for sensor 44>]},
                {"title": None, "sensor": <Sensor object for sensor 45>},
                {"title": None, "sensor": <Sensor object for sensor 46>}
            ]

        If the 'sensors_to_show' attribute is missing, the function defaults to showing two of the asset's sensors, grouped together if they share the same unit, or separately if not.
        If the suggest_default_sensors flag is set to False, the function will not suggest default sensors and will return an empty list if 'sensors_to_show' is not set.

        Note:
        Unauthorized sensors are filtered out, and a warning is logged. Only sensors the user has permission to access are included in the final result.
        """
        # If not set, use defaults (show first 2 sensors)
        if not self.sensors_to_show and suggest_default_sensors:
            sensors_to_show = self.sensors[:2]
            if (
                len(sensors_to_show) == 2
                and sensors_to_show[0].unit == sensors_to_show[1].unit
            ):
                # Sensors are shown together (e.g. they can share the same y-axis)
                return [{"title": None, "sensors": sensors_to_show}]
            # Otherwise, show separately
            return [{"title": None, "sensors": [sensor]} for sensor in sensors_to_show]

        sensor_ids_to_show = self.sensors_to_show
        # Import the schema for validation
        from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

        sensors_to_show_schema = SensorsToShowSchema()

        # Deserialize the sensor_ids_to_show using SensorsToShowSchema
        standardized_sensors_to_show = sensors_to_show_schema.deserialize(
            sensor_ids_to_show
        )

        sensor_id_allowlist = SensorsToShowSchema.flatten(standardized_sensors_to_show)

        # Only allow showing sensors from assets owned by the user's organization,
        # except in play mode, where any sensor may be shown
        accounts = [self.owner] if self.owner is not None else None
        if current_app.config.get("FLEXMEASURES_MODE") == "play":
            from flexmeasures.data.models.user import Account

            accounts = db.session.scalars(select(Account)).all()

        from flexmeasures.data.services.sensors import get_sensors

        accessible_sensor_map = {
            sensor.id: sensor
            for sensor in get_sensors(
                account=accounts,
                include_public_assets=True,
                sensor_id_allowlist=sensor_id_allowlist,
            )
        }

        # Build list of sensor objects that are accessible
        sensors_to_show = []
        missed_sensor_ids = []

        for entry in standardized_sensors_to_show:

            title = entry.get("title")
            sensors = entry.get("sensors")

            accessible_sensors = [
                accessible_sensor_map.get(sid)
                for sid in sensors
                if sid in accessible_sensor_map
            ]
            inaccessible = [sid for sid in sensors if sid not in accessible_sensor_map]
            missed_sensor_ids.extend(inaccessible)
            if accessible_sensors:
                sensors_to_show.append({"title": title, "sensors": accessible_sensors})

        if missed_sensor_ids:
            current_app.logger.warning(
                f"Cannot include sensor(s) {missed_sensor_ids} in sensors_to_show on asset {self}, as it is not accessible to user {current_user}."
            )
        return sensors_to_show

    @property
    def asset_type(self) -> GenericAssetType:
        """This property prepares for dropping the "generic" prefix later"""
        return self.generic_asset_type

    account_id = db.Column(
        db.Integer, db.ForeignKey("account.id", ondelete="CASCADE"), nullable=True
    )  # if null, asset is public

    owner = db.relationship(
        "Account",
        backref=db.backref(
            "generic_assets",
            foreign_keys=[account_id],
            lazy=True,
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    def get_path(self, separator: str = ">") -> str:
        if self.parent_asset is not None:
            return f"{self.parent_asset.get_path(separator=separator)}{separator}{self.name}"
        elif self.owner is None:
            return f"PUBLIC{separator}{self.name}"
        else:
            return f"{self.owner.get_path(separator=separator)}{separator}{self.name}"

    @property
    def offspring(self) -> list[GenericAsset]:
        """Returns a flattened list of all offspring, which is looked up recursively."""
        offspring = []

        for child in self.child_assets:
            offspring.extend(child.offspring)

        return offspring + self.child_assets

    @property
    def location(self) -> tuple[float, float] | None:
        location = (self.latitude, self.longitude)
        if None not in location:
            return location

    @hybrid_method
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (in km).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return geo_utils.earth_distance(self.location, other_location)

    @great_circle_distance.expression
    def great_circle_distance(self, **kwargs):
        """Query great circle distance (unclear if in km or in miles).

        Can be called with an object that has latitude and longitude properties, for example:

            great_circle_distance(object=asset)

        Can also be called with latitude and longitude parameters, for example:

            great_circle_distance(latitude=32, longitude=54)
            great_circle_distance(lat=32, lng=54)

        Requires the following Postgres extensions: earthdistance and cube.
        """
        other_location = geo_utils.parse_lat_lng(kwargs)
        if None in other_location:
            return None
        return func.earth_distance(
            func.ll_to_earth(self.latitude, self.longitude),
            func.ll_to_earth(*other_location),
        )

    def get_attribute(self, attribute: str, default: Any = None):
        if attribute in self.attributes:
            return self.attributes[attribute]
        if self.flex_context and attribute in self.flex_context:
            return self.flex_context[attribute]
        return default

    def has_attribute(self, attribute: str) -> bool:
        return attribute in self.attributes

    def set_attribute(self, attribute: str, value):
        if self.has_attribute(attribute):
            self.attributes[attribute] = value

    def get_flex_context(self) -> dict:
        """Reconstitutes the asset's serialized flex-context by gathering flex-contexts upwards in the asset tree.

        Flex-context fields of ancestors that are nearer have priority.
        We return once we collect all flex-context fields or reach the top asset.
        """
        from flexmeasures.data.schemas.scheduling import DBFlexContextSchema

        flex_context_field_names = set(DBFlexContextSchema.mapped_schema_keys.values())
        if self.flex_context:
            flex_context = self.flex_context.copy()
        else:
            flex_context = {}
        parent_asset = self.parent_asset
        while set(flex_context.keys()) != flex_context_field_names and parent_asset:
            flex_context = {**parent_asset.flex_context, **flex_context}
            parent_asset = parent_asset.parent_asset
        return flex_context

    def get_consumption_price_sensor(self):
        """Searches for consumption_price_sensor upwards on the asset tree"""

        from flexmeasures.data.models.time_series import Sensor

        flex_context = self.get_flex_context()
        sensor_id = flex_context.get("consumption-price-sensor")

        if sensor_id is None:
            consumption_price_data = flex_context.get("consumption-price")
            if consumption_price_data:
                sensor_id = consumption_price_data.get("sensor")
        if sensor_id:
            return Sensor.query.get(sensor_id) or None

        if self.parent_asset:
            return self.parent_asset.get_consumption_price_sensor()
        return None

    def get_production_price_sensor(self):
        """Searches for production_price_sensor upwards on the asset tree"""

        from flexmeasures.data.models.time_series import Sensor

        flex_context = self.get_flex_context()
        sensor_id = flex_context.get("production-price-sensor")

        if sensor_id is None:
            production_price_data = flex_context.get("production-price")
            if production_price_data:
                sensor_id = production_price_data.get("sensor")
        if sensor_id:
            return Sensor.query.get(sensor_id) or None
        if self.parent_asset:
            return self.parent_asset.get_production_price_sensor()
        return None

    def get_inflexible_device_sensors(self):
        """
        Searches for inflexible_device_sensors upwards on the asset tree
        This search will stop once any sensors are found (will not aggregate towards the top of the tree)
        """

        from flexmeasures.data.models.time_series import Sensor

        flex_context = self.get_flex_context()
        # Need to load inflexible_device_sensors manually as generic_asset does not get to SQLAlchemy session context.
        if flex_context.get("inflexible-device-sensors"):
            sensors = Sensor.query.filter(
                Sensor.id.in_(flex_context["inflexible-device-sensors"])
            ).all()
            return sensors or []
        if self.parent_asset:
            return self.parent_asset.get_inflexible_device_sensors()
        return []

    @property
    def has_power_sensors(self) -> bool:
        """True if at least one power sensor is attached"""
        return any([s.measures_power for s in self.sensors])

    @property
    def has_energy_sensors(self) -> bool:
        """True if at least one energy sensor is attached"""
        return any([s.measures_energy for s in self.sensors])

    def add_annotations(
        self,
        df: pd.DataFrame,
        annotation_type: str,
        commit_transaction: bool = False,
    ):
        """Add a data frame describing annotations to the database, and assign the annotations to this asset."""
        annotations = Annotation.add(df, annotation_type=annotation_type)
        self.annotations += annotations
        db.session.add(self)
        if commit_transaction:
            db.session.commit()

    def search_annotations(
        self,
        annotations_after: datetime | None = None,
        annotations_before: datetime | None = None,
        source: (
            DataSource | list[DataSource] | int | list[int] | str | list[str] | None
        ) = None,
        annotation_type: str = None,
        include_account_annotations: bool = False,
        as_frame: bool = False,
    ) -> list[Annotation] | pd.DataFrame:
        """Return annotations assigned to this asset, and optionally, also those assigned to the asset's account.

        The returned annotations do not include any annotations on public accounts.

        :param annotations_after: only return annotations that end after this datetime (exclusive)
        :param annotations_before: only return annotations that start before this datetime (exclusive)
        """
        parsed_sources = parse_source_arg(source)
        annotations = db.session.scalars(
            query_asset_annotations(
                asset_id=self.id,
                annotations_after=annotations_after,
                annotations_before=annotations_before,
                sources=parsed_sources,
                annotation_type=annotation_type,
            )
        ).all()
        if include_account_annotations and self.owner is not None:
            annotations += self.owner.search_annotations(
                annotations_after=annotations_after,
                annotations_before=annotations_before,
                source=source,
            )

        return to_annotation_frame(annotations) if as_frame else annotations

    def count_annotations(
        self,
        annotation_starts_after: datetime | None = None,  # deprecated
        annotations_after: datetime | None = None,
        annotation_ends_before: datetime | None = None,  # deprecated
        annotations_before: datetime | None = None,
        source: (
            DataSource | list[DataSource] | int | list[int] | str | list[str] | None
        ) = None,
        annotation_type: str = None,
    ) -> int:
        """Count the number of annotations assigned to this asset."""

        # todo: deprecate the 'annotation_starts_after' argument in favor of 'annotations_after' (announced v0.11.0)
        annotations_after = tb_utils.replace_deprecated_argument(
            "annotation_starts_after",
            annotation_starts_after,
            "annotations_after",
            annotations_after,
            required_argument=False,
        )

        # todo: deprecate the 'annotation_ends_before' argument in favor of 'annotations_before' (announced v0.11.0)
        annotations_before = tb_utils.replace_deprecated_argument(
            "annotation_ends_before",
            annotation_ends_before,
            "annotations_before",
            annotations_before,
            required_argument=False,
        )

        parsed_sources = parse_source_arg(source)
        return query_asset_annotations(
            asset_id=self.id,
            annotations_after=annotations_after,
            annotations_before=annotations_before,
            sources=parsed_sources,
            annotation_type=annotation_type,
        ).count()

    def chart(
        self,
        chart_type: str = "chart_for_multiple_sensors",
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        beliefs_after: datetime | None = None,
        beliefs_before: datetime | None = None,
        combine_legend: bool = True,
        source: (
            DataSource | list[DataSource] | int | list[int] | str | list[str] | None
        ) = None,
        include_data: bool = False,
        dataset_name: str | None = None,
        resolution: str | timedelta | None = None,
        **kwargs,
    ) -> dict:
        """Create a vega-lite chart showing sensor data.

        :param chart_type: currently only "bar_chart" # todo: where can we properly list the available chart types?
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param combine_legend: show a combined legend of all plots below the chart
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param include_data: if True, include data in the chart, or if False, exclude data
        :param dataset_name: optionally name the dataset used in the chart (the default name is sensor_<id>)
        :param resolution: optionally set the resolution of data being displayed
        :returns: JSON string defining vega-lite chart specs
        """
        processed_sensors_to_show = self.validate_sensors_to_show()
        sensors = flatten_unique(processed_sensors_to_show)

        for sensor in sensors:
            sensor.sensor_type = sensor.get_attribute("sensor_type", sensor.name)

        # Set up chart specification
        if dataset_name is None:
            dataset_name = "asset_" + str(self.id)
        if event_starts_after:
            kwargs["event_starts_after"] = event_starts_after
        if event_ends_before:
            kwargs["event_ends_before"] = event_ends_before
        chart_specs = chart_type_to_chart_specs(
            chart_type,
            sensors_to_show=processed_sensors_to_show,
            dataset_name=dataset_name,
            combine_legend=combine_legend,
            **kwargs,
        )

        if include_data:
            # Get data
            data = self.search_beliefs(
                sensors=sensors,
                as_json=True,
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                source=source,
                resolution=resolution,
            )

            # Combine chart specs and data
            chart_specs["datasets"] = {
                dataset_name: json.loads(data),
            }

        return chart_specs

    def search_beliefs(
        self,
        sensors: list["Sensor"] | None = None,  # noqa F821
        event_starts_after: datetime | None = None,
        event_ends_before: datetime | None = None,
        beliefs_after: datetime | None = None,
        beliefs_before: datetime | None = None,
        horizons_at_least: timedelta | None = None,
        horizons_at_most: timedelta | None = None,
        source: (
            DataSource | list[DataSource] | int | list[int] | str | list[str] | None
        ) = None,
        most_recent_beliefs_only: bool = True,
        most_recent_events_only: bool = False,
        as_json: bool = False,
        resolution: timedelta | None = None,
    ) -> BeliefsDataFrame | str:
        """Search all beliefs about events for all sensors of this asset

        If you don't set any filters, you get the most recent beliefs about all events.

        :param sensors: only return beliefs about events registered by these sensors
        :param event_starts_after: only return beliefs about events that start after this datetime (inclusive)
        :param event_ends_before: only return beliefs about events that end before this datetime (inclusive)
        :param beliefs_after: only return beliefs formed after this datetime (inclusive)
        :param beliefs_before: only return beliefs formed before this datetime (inclusive)
        :param horizons_at_least: only return beliefs with a belief horizon equal or greater than this timedelta (for example, use timedelta(0) to get ante knowledge time beliefs)
        :param horizons_at_most: only return beliefs with a belief horizon equal or less than this timedelta (for example, use timedelta(0) to get post knowledge time beliefs)
        :param source: search only beliefs by this source (pass the DataSource, or its name or id) or list of sources
        :param most_recent_events_only: only return (post knowledge time) beliefs for the most recent event (maximum event start)
        :param as_json: return beliefs in JSON format (e.g. for use in charts) rather than as BeliefsDataFrame
        :param resolution: optionally set the resolution of data being displayed
        :returns: dictionary of BeliefsDataFrames or JSON string (if as_json is True)
        """
        bdf_dict = {}
        if sensors is None:
            sensors = self.sensors

        _, factors = find_smallest_common_unit(
            list(set([sensor.unit for sensor in sensors]))
        )

        for sensor in sensors:
            bdf_dict[sensor] = sensor.search_beliefs(
                event_starts_after=event_starts_after,
                event_ends_before=event_ends_before,
                beliefs_after=beliefs_after,
                beliefs_before=beliefs_before,
                horizons_at_least=horizons_at_least,
                horizons_at_most=horizons_at_most,
                source=source,
                most_recent_beliefs_only=most_recent_beliefs_only,
                most_recent_events_only=most_recent_events_only,
                one_deterministic_belief_per_event_per_source=True,
                resolution=resolution,
            )
        if as_json:
            from flexmeasures.data.services.time_series import simplify_index

            if sensors:
                minimum_resampling_resolution = determine_minimum_resampling_resolution(
                    [bdf.event_resolution for bdf in bdf_dict.values()]
                )
                if resolution is not None:
                    minimum_resampling_resolution = resolution
                df_dict = {}
                for sensor, bdf in bdf_dict.items():
                    if bdf.event_resolution > timedelta(0):
                        bdf = bdf.resample_events(minimum_resampling_resolution)
                    bdf["belief_horizon"] = bdf.belief_horizons.to_numpy()
                    df = simplify_index(
                        bdf,
                        index_levels_to_columns=(
                            ["source"]
                            if most_recent_beliefs_only
                            else ["belief_time", "source"]
                        ),
                    ).set_index(
                        (
                            ["source"]
                            if most_recent_beliefs_only
                            else ["belief_time", "source"]
                        ),
                        append=True,
                    )
                    df["sensor"] = sensor  # or some JSONifiable representation
                    df["scale_factor"] = factors[sensor.unit]
                    df = df.set_index(["sensor"], append=True)
                    df_dict[sensor.id] = df
                df = pd.concat([df.reset_index() for df in df_dict.values()]).set_index(
                    ["event_start", "source", "sensor"]
                )
            else:
                df = simplify_index(
                    BeliefsDataFrame(),
                    index_levels_to_columns=(
                        ["source"]
                        if most_recent_beliefs_only
                        else ["belief_time", "source"]
                    ),
                ).set_index(
                    (
                        ["source"]
                        if most_recent_beliefs_only
                        else ["belief_time", "source"]
                    ),
                    append=True,
                )
                df["sensor"] = {}  # ensure the same columns as a non-empty frame
            df = df.reset_index()
            df["source"] = df["source"].apply(lambda x: x.as_dict)
            df["sensor"] = df["sensor"].apply(lambda x: x.as_dict)
            df["sensor_unit"] = df["sensor"].apply(lambda x: x["sensor_unit"])
            df["event_value"] = df.apply(
                lambda row: (
                    pd.to_datetime(row["event_value"], unit="s", origin="unix")
                    .tz_localize("UTC")
                    .tz_convert(self.timezone)
                    if row["sensor_unit"] == "s" and pd.notnull(row["event_value"])
                    else row["event_value"]
                ),
                axis=1,
            )
            return df.to_json(orient="records")
        return bdf_dict

    @property
    def timezone(
        self,
    ) -> str:
        """Timezone relevant to the asset.

        If a timezone is not given as an attribute of the asset, it is taken from one of its sensors.
        """
        if self.has_attribute("timezone"):
            return self.get_attribute("timezone")
        if self.sensors:
            return self.sensors[0].timezone
        return "UTC"

    @property
    def timerange(self) -> dict[str, datetime]:
        """Time range for which sensor data exists.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        return self.get_timerange(self.sensors)

    @property
    def timerange_of_sensors_to_show(self) -> dict[str, datetime]:
        """Time range for which sensor data exists, for sensors to show.

        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        return self.get_timerange(self.validate_sensors_to_show())

    @classmethod
    def get_timerange(cls, sensors: list["Sensor"]) -> dict[str, datetime]:  # noqa F821
        """Time range for which sensor data exists.

        :param sensors: sensors to check
        :returns: dictionary with start and end, for example:
                  {
                      'start': datetime.datetime(2020, 12, 3, 14, 0, tzinfo=pytz.utc),
                      'end': datetime.datetime(2020, 12, 3, 14, 30, tzinfo=pytz.utc)
                  }
        """
        sensor_ids = [s.id for s in flatten_unique(sensors)]
        start, end = get_timerange(sensor_ids)
        return dict(start=start, end=end)

    def set_inflexible_sensors(self, inflexible_sensor_ids: list[int]) -> None:
        """Set inflexible sensors for this asset.

        :param inflexible_sensor_ids: list of sensor ids
        """
        from flexmeasures.data.models.time_series import Sensor

        # -1 choice corresponds to "--Select sensor id--" which means no sensor is selected
        # and all linked sensors should be unlinked
        if len(inflexible_sensor_ids) == 1 and inflexible_sensor_ids[0] == -1:
            self.inflexible_device_sensors = []
        else:
            self.inflexible_device_sensors = Sensor.query.filter(
                Sensor.id.in_(inflexible_sensor_ids)
            ).all()
        db.session.add(self)


def create_generic_asset(generic_asset_type: str, **kwargs) -> GenericAsset:
    """Create a GenericAsset and assigns it an id.

    :param generic_asset_type: "asset", "market" or "weather_sensor"
    :param kwargs:              should have values for keys "name", and:
                                - "asset_type_name" or "asset_type" when generic_asset_type is "asset"
                                - "market_type_name" or "market_type" when generic_asset_type is "market"
                                - "weather_sensor_type_name" or "weather_sensor_type" when generic_asset_type is "weather_sensor"
                                - alternatively, "sensor_type" is also fine
    :returns:                   the created GenericAsset
    """
    asset_type_name = kwargs.pop(f"{generic_asset_type}_type_name", None)
    if asset_type_name is None:
        if f"{generic_asset_type}_type" in kwargs:
            asset_type_name = kwargs.pop(f"{generic_asset_type}_type").name
        else:
            asset_type_name = kwargs.pop("sensor_type").name
    generic_asset_type = db.session.execute(
        select(GenericAssetType).filter_by(name=asset_type_name)
    ).scalar_one_or_none()
    if generic_asset_type is None:
        raise ValueError(f"Cannot find GenericAssetType {asset_type_name} in database.")

    new_generic_asset = GenericAsset(
        name=kwargs["name"],
        generic_asset_type_id=generic_asset_type.id,
        attributes=kwargs["attributes"] if "attributes" in kwargs else {},
    )
    for arg in ("latitude", "longitude", "account_id"):
        if arg in kwargs:
            setattr(new_generic_asset, arg, kwargs[arg])
    db.session.add(new_generic_asset)
    db.session.flush()  # generates the pkey for new_generic_asset

    return new_generic_asset


def assets_share_location(assets: list[GenericAsset]) -> bool:
    """
    Return True if all assets in this list are located on the same spot.
    TODO: In the future, we might soften this to compare if assets are in the same "housing" or "site".
    """
    if not assets:
        return True
    return all([a.location == assets[0].location for a in assets])


def get_center_location_of_assets(user: User | None) -> tuple[float, float]:
    """
    Find the center position between all generic assets of the user's account.
    """
    query = (
        "Select (min(latitude) + max(latitude)) / 2 as latitude,"
        " (min(longitude) + max(longitude)) / 2 as longitude"
        " from generic_asset"
    )
    if user is None:
        user = current_user
    query += f" where generic_asset.account_id = {user.account_id}"
    locations: list[Row] = db.session.execute(text(query + ";")).fetchall()
    if (
        len(locations) == 0
        or locations[0].latitude is None
        or locations[0].longitude is None
    ):
        return 52.366, 4.904  # Amsterdam, NL
    return locations[0].latitude, locations[0].longitude
