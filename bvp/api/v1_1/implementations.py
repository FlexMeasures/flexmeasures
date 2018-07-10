from typing import Tuple, Union

import isodate
from flask_json import as_json

from bvp.api.common.responses import request_processed
from bvp.api.common.utils.api_utils import parse_entity_address
from bvp.api.common.utils.validators import (
    type_accepted,
    units_accepted,
    connections_required,
    resolutions_accepted,
    horizon_accepted,
    period_required,
)
from bvp.data.models.assets import Asset, Power


@type_accepted("GetPrognosisRequest")
@units_accepted("MW")
@resolutions_accepted("PT15M")
@connections_required
@horizon_accepted
@period_required
@as_json
def get_prognosis_response(
    unit, resolution, connection_groups, horizon, start, duration
) -> Union[dict, Tuple[dict, int]]:

    # Todo: if resolution is not specified, request should be accepted and collect function should still work

    # Todo: if resolution is specified, it should be converted properly to a pandas dataframe frequency
    if resolution == "PT15M":
        resolution = "15T"

    end = start + duration
    for group in connection_groups:
        asset_names = []
        for connection in group:
            scheme_and_naming_authority, owner_id, asset_id = parse_entity_address(
                connection
            )
            asset = Asset.query.filter(Asset.id == asset_id).one_or_none()
            asset_names.append(asset.name)
        group_response = {"connections": group}
        ts_df = Power.collect(
            generic_asset_names=asset_names,
            start=start,
            end=end,
            resolution=resolution,
            horizon=horizon,
            sum_multiple=True,
        )
        print(ts_df)
        if ts_df.empty:
            group_response["values"] = []
        else:
            group_response["values"] = ts_df.y

    response = (
        group_response
    )  # Todo: implement new function to simplify zipper connection/value_groups

    add_to_response = {
        "start": isodate.datetime_isoformat(start),
        "duration": isodate.duration_isoformat(duration),
        "unit": unit,
    }

    d, s = request_processed()
    return dict(**response, **add_to_response, **d), s
