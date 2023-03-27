from __future__ import annotations

from typing import Union, Optional

from flexmeasures import User
from flexmeasures.utils.coding_utils import deprecated
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.data_sources import (
    get_or_create_source as get_or_create_source_new,
)
from flexmeasures.data.services.data_sources import (
    get_source_or_none as get_source_or_none_new,
)


@deprecated(get_or_create_source_new)
def get_or_create_source(
    source: Union[User, str],
    source_type: Optional[str] = None,
    model: Optional[str] = None,
    flush: bool = True,
) -> DataSource:
    return get_or_create_source_new(source, source_type, model, flush)


@deprecated(get_source_or_none_new)
def get_source_or_none(
    source: int | str, source_type: str | None = None
) -> DataSource | None:
    """
    :param source:      source id
    :param source_type: optionally, filter by source type
    """

    return get_source_or_none_new(source, source_type)
