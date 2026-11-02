"""Fields for choosing which chart to draw."""

from __future__ import annotations

from marshmallow import fields, validate

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
        description += f". The legacy values {legacy_names} are still accepted"
    return description


class AssetChartTypeField(fields.Str):
    """The name of an asset chart type, validated against the registry of asset chart types.

    An unknown name fails validation, which the API answers with a 422.
    """

    def __init__(self, accept_legacy_names: bool = False, **kwargs):
        """Set up the field.

        :param accept_legacy_names: whether to also accept the names the chart endpoint took before the chart types had public names,
                                    mapping them to the public names.
        """
        self.accept_legacy_names = accept_legacy_names
        kwargs["validate"] = validate.OneOf(list(ASSET_CHART_TYPES))
        metadata = kwargs.setdefault("metadata", {})
        metadata.setdefault("example", DEFAULT_ASSET_CHART_TYPE)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs) -> str:
        name = super()._deserialize(value, attr, data, **kwargs)
        if self.accept_legacy_names:
            return LEGACY_ASSET_CHART_TYPE_NAMES.get(name, name)
        return name
