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
        description += (
            f". The legacy values {legacy_names} are deprecated, but still accepted"
        )
    return description


class AssetChartTypeField(fields.Str):
    """The name of an asset chart type, validated against the registry of asset chart types.

    An unknown name fails validation, which the API answers with a 422.
    """

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
        :param empty_means_absent:  whether to read an empty value as no chart type (None), rather than refuse it.
        """
        self.accept_legacy_names = accept_legacy_names
        self.empty_means_absent = empty_means_absent
        extra_validators = kwargs.pop("validate", None) or []
        if callable(extra_validators):
            extra_validators = [extra_validators]
        kwargs["validate"] = [
            validate.OneOf(list(ASSET_CHART_TYPES)),
            *extra_validators,
        ]
        metadata = kwargs.setdefault("metadata", {})
        metadata.setdefault("example", DEFAULT_ASSET_CHART_TYPE)
        super().__init__(**kwargs)

    def deserialize(self, value, attr=None, data=None, **kwargs):
        if self.empty_means_absent and value == "":
            return None
        return super().deserialize(value, attr, data, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs) -> str:
        name = super()._deserialize(value, attr, data, **kwargs)
        if self.accept_legacy_names:
            return LEGACY_ASSET_CHART_TYPE_NAMES.get(name, name)
        return name
