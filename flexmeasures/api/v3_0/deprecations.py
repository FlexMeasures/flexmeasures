from __future__ import annotations

from datetime import datetime, timezone

from flexmeasures.utils.time_utils import to_http_time


# TODO: In another iteration, this will be saved in a more generic deprecations structure,
#       With the ability for hosts to set the dates or other specifics
#       to their own cadence.
JOB_RESPONSE_FIELDS_DEPRECATION_DATE = to_http_time(
    datetime(2026, 8, 1, tzinfo=timezone.utc)
)
