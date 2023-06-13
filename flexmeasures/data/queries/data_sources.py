from __future__ import annotations

from flexmeasures import User
from flexmeasures.utils.coding_utils import deprecated
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.services.data_sources import (
    get_or_create_source as get_or_create_source_new,
)
from flexmeasures.data.services.data_sources import (
    get_source_or_none as get_source_or_none_new,
)


@deprecated(get_or_create_source_new, "0.14")
def get_or_create_source(
    source: User | str,
    source_type: str | None = None,
    model: str | None = None,
    flush: bool = True,
) -> DataSource:
    return get_or_create_source_new(source, source_type, model, flush=flush)


@deprecated(get_source_or_none_new, "0.14")
def get_source_or_none(
    source: int | str, source_type: str | None = None
) -> DataSource | None:
    """
    :param source:      source id
    :param source_type: optionally, filter by source type
    """

    return get_source_or_none_new(source, source_type)
