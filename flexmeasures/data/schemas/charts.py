"""Fields for choosing which chart to draw."""

from __future__ import annotations

from marshmallow import ValidationError, fields, validate

from flexmeasures.data.models.charts.chart_types import (
    ASSET_CHART_TYPES,
    DEFAULT_ASSET_CHART_TYPE,
    LEGACY_ASSET_CHART_TYPE_NAMES,
)


def describe_asset_chart_types(include_legacy_names: bool = False) -> str:
    """List the asset chart types from the registry, for a field description.

    :param include_legacy_names: whether to also mention the legacy names that are still accepted.
    """
    description = "; ".join(
        f"'{name}' ({chart_type.description})"
        for name, chart_type in ASSET_CHART_TYPES.items()
    )
    if include_legacy_names:
        legacy_names = " and ".join(
            f"'{legacy_name}' (for '{name}')"
            for legacy_name, name in LEGACY_ASSET_CHART_TYPE_NAMES.items()
        )
        description += (
            f". The legacy values {legacy_names} are deprecated, but still accepted"
        )
    return description


class RegisteredAssetChartType(validate.Validator):
    """Validate that a name is in the registry of asset chart types, reading the registry each time it validates.

    Unlike validate.OneOf, which copies its choices when it is set up,
    this validator also accepts the chart types that plugins register after the field was made.
    """

    error = "Must be one of: {choices}."

    @property
    def choices(self) -> list[str]:
        """The names of the registered asset chart types (which the OpenAPI specs list as the field's enum)."""
        return list(ASSET_CHART_TYPES)

    def _repr_args(self) -> str:
        return f"choices={self.choices!r}"

    def __call__(self, value: str) -> str:
        if value not in ASSET_CHART_TYPES:
            raise ValidationError(self.error.format(choices=", ".join(self.choices)))
        return value


class AssetChartTypeField(fields.Str):
    """The name of an asset chart type, validated against the registry of asset chart types.

    The registry is read when a name is validated, so the field also accepts chart types that plugins register.
    An unknown name fails validation, which the API answers with a 422.
    """

    def __init__(self, accept_legacy_names: bool = False, **kwargs):
        """Set up the field.

        The name is checked against the registry first, and then by any validators passed as validate.
        The legacy names, if accepted, are mapped before that check, so they are not among the allowed values (the enum, in OpenAPI).

        :param accept_legacy_names: whether to also accept the names the chart endpoint took before the chart types had public names,
                                    mapping them to the public names.
        """
        self.accept_legacy_names = accept_legacy_names
        extra_validators = kwargs.pop("validate", None) or []
        if callable(extra_validators):
            extra_validators = [extra_validators]
        kwargs["validate"] = [
            RegisteredAssetChartType(),
            *extra_validators,
        ]
        metadata = kwargs.setdefault("metadata", {})
        metadata.setdefault("example", DEFAULT_ASSET_CHART_TYPE)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs) -> str:
        name = super()._deserialize(value, attr, data, **kwargs)
        if self.accept_legacy_names:
            return LEGACY_ASSET_CHART_TYPE_NAMES.get(name, name)
        return name
