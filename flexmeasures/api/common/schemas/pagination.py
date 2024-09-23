from __future__ import annotations

from marshmallow import fields

from flexmeasures.data.schemas.utils import FMValidationError


class PageField(fields.Integer):
    """
    Field that represents a page number or items per page. It de-serializes from the page/per_page number to an integer.
    """

    def _deserialize(self, page: int, attr, obj, **kwargs) -> int:
        page = int(page)

        if page < 1:
            raise FMValidationError("Page/Per Page number must be at least 1")
        return page

    def _serialize(self, page: int, attr, data, **kwargs) -> int:
        return page
