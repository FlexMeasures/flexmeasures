from typing import Tuple, Union

from flask_json import as_json

from bvp.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    connections_required,
    optional_sources_accepted,
    optional_resolutions_accepted,
    optional_horizon_accepted,
    period_required,
)
from bvp.api.v1.implementations import collect_connection_and_value_groups


@type_accepted("GetPrognosisRequest")
@units_accepted("MW")
@optional_resolutions_accepted("PT15M")
@connections_required
@optional_sources_accepted()
@optional_horizon_accepted()
@period_required
@as_json
def get_prognosis_response(
    unit,
    resolution,
    connection_groups,
    horizon,
    start,
    duration,
    preferred_source_ids,
    fallback_source_ids,
) -> Union[dict, Tuple[dict, int]]:

    return collect_connection_and_value_groups(
        unit,
        resolution,
        connection_groups,
        horizon,
        start,
        duration,
        preferred_source_ids,
        fallback_source_ids,
    )
