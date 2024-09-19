from __future__ import annotations

from flask import abort
from marshmallow import fields


class PageField(fields.Integer):
    """
    Field that represents a page number or items per page. It de-serializes from the page/per_page number to an integer.
    """

    def _deserialize(self, page: int, attr, obj, **kwargs) -> int:
        page = int(page)

        if page < 1:
            raise abort(422, "Page/Per Page number must be at least 1")
        return page

    def _serialize(self, page: int, attr, data, **kwargs) -> int:
        return page
