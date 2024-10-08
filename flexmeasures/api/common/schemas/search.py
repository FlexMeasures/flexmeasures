from __future__ import annotations

from shlex import join, split

from marshmallow import fields, ValidationError


class SearchFilterField(fields.Str):
    """Field that represents a search filter."""

    def _deserialize(self, value, attr, data, **kwargs) -> list[str]:
        try:
            search_terms = split(value)
        except ValueError as e:
            raise ValidationError(str(e))
        return search_terms

    def _serialize(self, value: list[str], attr, obj, **kwargs) -> str:
        return join(value)
