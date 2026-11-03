"""Fields for choosing which chart to draw."""

from __future__ import annotations

from marshmallow import ValidationError, fields, validate

from flexmeasures.data.models.charts.chart_types import (
    ASSET_CHART_TYPE_REGISTRY,
    DEFAULT_ASSET_CHART_TYPE,
    DEFAULT_SENSOR_CHART_TYPE,
    SENSOR_CHART_TYPE_REGISTRY,
    ChartTypeRegistry,
)


def describe_chart_types(
    registry: ChartTypeRegistry, include_legacy_names: bool = False
) -> str:
    """List the chart types from a registry, for a field description.

    :param registry: the registry of asset or sensor chart types.
    :param include_legacy_names: whether to also mention the legacy names that are still accepted.
    """
    description = "; ".join(
        f"'{name}' ({chart_type.description})"
        for name, chart_type in registry.chart_types.items()
    )
    if include_legacy_names and registry.legacy_names:
        legacy_names = " and ".join(
            f"'{legacy_name}' (for '{name}')"
            for legacy_name, name in registry.legacy_names.items()
        )
        description += (
            f". The legacy values {legacy_names} are deprecated, but still accepted"
        )
    return description


def describe_asset_chart_types(include_legacy_names: bool = False) -> str:
    """List the asset chart types from the registry, for a field description.

    :param include_legacy_names: whether to also mention the legacy names that are still accepted.
    """
    return describe_chart_types(
        ASSET_CHART_TYPE_REGISTRY, include_legacy_names=include_legacy_names
    )


def describe_sensor_chart_types(include_legacy_names: bool = False) -> str:
    """List the sensor chart types from the registry, for a field description.

    :param include_legacy_names: whether to also mention the legacy names that are still accepted.
    """
    return describe_chart_types(
        SENSOR_CHART_TYPE_REGISTRY, include_legacy_names=include_legacy_names
    )


class RegisteredChartType(validate.Validator):
    """Validate that a name is in a registry of chart types, reading the registry each time it validates.

    Unlike validate.OneOf, which copies its choices when it is set up,
    this validator also accepts the chart types that plugins register after the field was made.
    """

    error = "Must be one of: {choices}."

    def __init__(self, registry: ChartTypeRegistry):
        self.registry = registry

    @property
    def choices(self) -> list[str]:
        """The names of the registered chart types (which the OpenAPI specs list as the field's enum)."""
        return list(self.registry.chart_types)

    def _repr_args(self) -> str:
        return f"choices={self.choices!r}"

    def __call__(self, value: str) -> str:
        if value not in self.registry.chart_types:
            raise ValidationError(self.error.format(choices=", ".join(self.choices)))
        return value


class RegisteredAssetChartType(RegisteredChartType):
    """Validate that a name is in the registry of asset chart types, reading the registry each time it validates."""

    def __init__(self):
        super().__init__(ASSET_CHART_TYPE_REGISTRY)


class RegisteredSensorChartType(RegisteredChartType):
    """Validate that a name is in the registry of sensor chart types, reading the registry each time it validates."""

    def __init__(self):
        super().__init__(SENSOR_CHART_TYPE_REGISTRY)


class ChartTypeField(fields.Str):
    """The name of a chart type, validated against a registry of chart types.

    The registry is read when a name is validated, so the field also accepts chart types that plugins register.
    An unknown name fails validation, which the API answers with a 422.
    Subclasses say which registry, and which chart type serves as the example.
    """

    registry: ChartTypeRegistry
    default_chart_type: str

    def __init__(
        self,
        accept_legacy_names: bool = False,
        empty_means_absent: bool = False,
        **kwargs,
    ):
        """Set up the field.

        The name is checked against the registry first, and then by any validators passed as validate.
        The legacy names, if accepted, are mapped before that check, so they are not among the allowed values (the enum, in OpenAPI).

        :param accept_legacy_names: whether to also accept the names the chart endpoint took before the chart types had public names,
                                    mapping them to the public names.
        :param empty_means_absent: whether to read an empty value as no chart type (None), rather than refuse it.
        """
        self.accept_legacy_names = accept_legacy_names
        self.empty_means_absent = empty_means_absent
        extra_validators = kwargs.pop("validate", None) or []
        if callable(extra_validators):
            extra_validators = [extra_validators]
        kwargs["validate"] = [
            RegisteredChartType(self.registry),
            *extra_validators,
        ]
        metadata = kwargs.setdefault("metadata", {})
        metadata.setdefault("example", self.default_chart_type)
        super().__init__(**kwargs)

    def deserialize(self, value, attr=None, data=None, **kwargs):
        if self.empty_means_absent and value == "":
            return None
        return super().deserialize(value, attr, data, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs) -> str:
        name = super()._deserialize(value, attr, data, **kwargs)
        if self.accept_legacy_names:
            return self.registry.public_name(name)
        return name


class AssetChartTypeField(ChartTypeField):
    """The name of an asset chart type, validated against the registry of asset chart types."""

    registry = ASSET_CHART_TYPE_REGISTRY
    default_chart_type = DEFAULT_ASSET_CHART_TYPE


class SensorChartTypeField(ChartTypeField):
    """The name of a sensor chart type, validated against the registry of sensor chart types."""

    registry = SENSOR_CHART_TYPE_REGISTRY
    default_chart_type = DEFAULT_SENSOR_CHART_TYPE
