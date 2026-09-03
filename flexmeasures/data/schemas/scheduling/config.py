"""What makes up a scheduler's configuration, as recorded on its data source."""

from __future__ import annotations

from marshmallow import Schema, fields

#: Flex-config fields which state what was true at one moment, rather than where to look it up.
#: A recurring automation would carry such a value into every later run, long after the moment it described,
#: and a data source recording one would be a new source on every run.
MOMENTARY_FLEX_FIELDS = ("soc-at-start",)

#: Keys which mark a value as describing one moment or period, as a time series segment does.
_MOMENT_KEYS = ("datetime", "start", "end")


def _describes_a_moment(value) -> bool:
    """Whether this value pins itself to a moment, as a time series segment does."""
    return isinstance(value, dict) and any(key in value for key in _MOMENT_KEYS)


def _walk_momentary_fields(value, path: str, drop: bool):
    """Find, and optionally drop, the parts of a flex config which describe one moment.

    Returns the value (with those parts removed when `drop`) and the paths at which they were found.
    """
    found: list[str] = []
    if isinstance(value, dict):
        if _describes_a_moment(value):
            return (None if drop else value), [path]
        kept = {}
        for key, item in value.items():
            if key in MOMENTARY_FLEX_FIELDS:
                found.append(f"{path}.{key}")
                if drop:
                    continue
                kept[key] = item
                continue
            item, item_found = _walk_momentary_fields(item, f"{path}.{key}", drop)
            found += item_found
            kept[key] = item
        return kept, found
    if isinstance(value, list):
        kept = []
        for index, item in enumerate(value):
            item, item_found = _walk_momentary_fields(item, f"{path}[{index}]", drop)
            found += item_found
            if drop and item is None:
                continue
            kept.append(item)
        return kept, found
    return value, found


def find_momentary_flex_config_fields(message: dict) -> list[str]:
    """Find the flex config fields which describe one moment, rather than the site and its devices.

    A schedule automation recomputes its schedule on every run, so a value tied to a fixed moment is stale on the next one.
    Sensor references and plain quantities are fine: they say where to look, or what always holds, rather than what was true once.
    """
    found: list[str] = []
    for key in ("flex-model", "flex-context"):
        _, key_found = _walk_momentary_fields(message.get(key), key, drop=False)
        found += key_found
    return sorted(set(found))


def strip_momentary_flex_fields(value):
    """Return the flex config without the parts which describe one moment.

    A scheduler's data source is identified by its configuration, so anything that changes from run to run has to stay out of it.
    A state of charge measured at the start of one schedule, or a target at one datetime, would otherwise make every run a new data source.
    """
    stripped, _ = _walk_momentary_fields(value, "", drop=True)
    return stripped


class SchedulerConfigSchema(Schema):
    """The configuration of a scheduler: which asset it schedules, and the flex config it uses.

    Together with the scheduler's class and version, this is what tells one scheduler data source from another,
    so that a schedule can be traced back to the configuration it was computed under.
    Timing fields are deliberately absent: start, end, resolution and belief time differ from run to run,
    and are the scheduler's parameters rather than its configuration.

    The flex config is kept in its serialized form, as the trigger message and the asset tree spell it,
    because that is the form every scheduler shares.
    Deserialized flex configs hold sensors, quantities and time series, which each scheduler resolves in its own way.
    """

    asset = fields.Integer(
        required=False,
        allow_none=True,
        metadata=dict(
            description="ID of the asset (or of the sensor's asset) that this scheduler schedules.",
        ),
    )
    flex_model = fields.Raw(
        attribute="flex-model",
        data_key="flex-model",
        required=False,
        allow_none=True,
        metadata=dict(
            description="The flex-model the scheduler uses, after merging the trigger message with what the asset tree stores.",
        ),
    )
    flex_context = fields.Raw(
        attribute="flex-context",
        data_key="flex-context",
        required=False,
        allow_none=True,
        metadata=dict(
            description="The flex-context the scheduler uses, after merging the trigger message with what the asset tree stores.",
        ),
    )
