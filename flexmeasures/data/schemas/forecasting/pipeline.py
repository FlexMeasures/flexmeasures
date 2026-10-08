from __future__ import annotations

import logging
import os

from datetime import datetime, timedelta
from isodate.duration import Duration
import pandas as pd

from marshmallow import (
    fields,
    Schema,
    validate,
    validates_schema,
    pre_load,
    pre_dump,
    post_load,
    post_dump,
    ValidationError,
)

from flexmeasures.data.schemas import SensorIdField
from flexmeasures.data.schemas.utils import snake_to_kebab
from flexmeasures.data.schemas.forecasting.references import (
    AUTO_SENSOR,
    AutoSensorReference,
    ForecastInputField,
)
from flexmeasures.data.schemas.sensors import (
    SensorIdOrReferenceField,
    SensorReference,
)
from flexmeasures.data.schemas.times import (
    AwareDateTimeField,
    AwareDateTimeOrDateField,
    DurationField,
    PlanningDurationField,
)
from flexmeasures.data.models.forecasting.utils import floor_to_resolution
from flexmeasures.utils.bound_utils import bound_validation_errors
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.utils.time_utils import server_now
from flexmeasures.data.models.time_series import Sensor

DEFAULT_TRAIN_PERIOD = timedelta(days=30)


def _fixed_length_or_none(value) -> timedelta | None:
    """Return a duration as a timedelta, or None when it is not one of fixed length.

    A duration given in years or months parses to a Duration rather than a timedelta,
    and the two cannot be compared, so anything that compares durations has to know which it has.
    """
    try:
        parsed = DurationField().deserialize(value)
    except ValidationError:
        return None
    return parsed if isinstance(parsed, timedelta) else None


class AnnotationRegressorSchema(Schema):
    """Schema for a single annotation regressor in the forecasting pipeline config."""

    account = AccountIdField(
        allow_none=True,
        metadata={"description": "Account ID whose annotations to use."},
    )
    asset = GenericAssetIdField(
        allow_none=True,
        metadata={"description": "Asset ID whose annotations to use."},
    )
    sensor = SensorIdField(
        allow_none=True,
        metadata={"description": "Sensor ID whose annotations to use."},
    )
    annotation_type = fields.Str(
        data_key="annotation-type",
        load_default="holiday",
        metadata={
            "description": "Type of annotation to use (e.g. 'holiday', 'label', 'alert'). Defaults to 'holiday'."
        },
    )
    name = fields.Str(
        load_default=None,
        metadata={
            "description": "Human-readable column name for this regressor. Defaults to 'annotation_regressor_<index>'."
        },
    )

    @post_dump
    def remove_none_values(self, data, **kwargs):
        """Omit null fields from the serialised config to keep it clean."""
        return {k: v for k, v in data.items() if v is not None}

    @pre_dump
    def skip_empty_sources(self, data, **kwargs):
        """Omit empty sources before custom ID fields serialise objects."""
        return {k: v for k, v in data.items() if v is not None}

    @validates_schema
    def validate_single_source(self, data: dict, **kwargs):
        sources = [
            source_key
            for source_key in ("account", "asset", "sensor")
            if data.get(source_key) is not None
        ]
        if len(sources) != 1:
            raise ValidationError("Specify exactly one of account, asset, or sensor.")


class TrainPredictPipelineConfigSchema(Schema):

    model = fields.String(load_default="CustomLGBM")
    future_regressors = fields.List(
        ForecastInputField(),
        data_key="future-regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs or sensor references to be treated only as future regressors."
                " A reference can filter by source, and can carry lower, upper and snap bounds that clean this sensor's readings before the model trains on them."
                " Use this if only forecasts recorded on this sensor matter as a regressor."
                " Write 'auto' in place of a sensor ID to mean the sensor being forecast, as in {'sensor': 'auto', 'lower': '0 kW'}, which says which of its sources to train on and how to clean its readings."
                " See [choosing which data sources to train on](https://flexmeasures.readthedocs.io/latest/features/forecasting.html#choosing-which-data-sources-to-train-on)."
            ),
            "example": [
                {"sensor": 2093, "sources": [12, 13]},
                {"sensor": 2094, "source-types": ["forecaster"]},
            ],
            "cli": {
                "option": "--future-regressors",
            },
        },
    )
    past_regressors = fields.List(
        ForecastInputField(),
        data_key="past-regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs or sensor references to be treated only as past regressors."
                " A reference can filter by source, and can carry lower, upper and snap bounds that clean this sensor's readings before the model trains on them."
                " Use this if only realizations recorded on this sensor matter as a regressor."
                " Write 'auto' in place of a sensor ID to mean the sensor being forecast, as in {'sensor': 'auto', 'lower': '0 kW'}, which says which of its sources to train on and how to clean its readings."
                " See [choosing which data sources to train on](https://flexmeasures.readthedocs.io/latest/features/forecasting.html#choosing-which-data-sources-to-train-on)."
            ),
            "example": [{"sensor": 2095, "exclude-source-types": ["forecaster"]}],
            "cli": {
                "option": "--past-regressors",
            },
        },
    )
    regressors = fields.List(
        ForecastInputField(),
        data_key="regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs or sensor references used as both past and future regressors."
                " A reference can filter by source, and can carry lower, upper and snap bounds that clean this sensor's readings before the model trains on them."
                " Use this if both realizations and forecasts recorded on this sensor matter as a regressor."
                " Write 'auto' in place of a sensor ID to mean the sensor being forecast, as in {'sensor': 'auto', 'lower': '0 kW'}, which says which of its sources to train on and how to clean its readings."
                " See [choosing which data sources to train on](https://flexmeasures.readthedocs.io/latest/features/forecasting.html#choosing-which-data-sources-to-train-on)."
            ),
            "example": [
                {"sensor": 2093, "sources": [12, 13]},
                {"sensor": 2094, "source-account": [4]},
            ],
            "cli": {
                "option": "--regressors",
            },
        },
    )
    annotation_regressors = fields.List(
        fields.Nested(AnnotationRegressorSchema()),
        data_key="annotation-regressors",
        load_default=[],
        metadata={
            "description": (
                "Annotation sources to use as binary future regressors. "
                "Each entry must specify 'account', 'asset', or 'sensor' (ID), and optionally "
                "'annotation-type' (default: 'holiday') and 'name' (default: auto-generated). "
                "Annotations are converted to a binary 0/1 time series: 1 during annotated periods."
            ),
            "example": [
                {"account": 1, "annotation-type": "holiday", "name": "holidays"}
            ],
            "cli": {
                "option": "--annotation-regressors",
            },
        },
    )
    model_params = fields.Dict(
        keys=fields.Str(),
        data_key="model-params",
        load_default=None,
        allow_none=True,
        metadata={
            "description": (
                "LightGBM parameter overrides, merged over the defaults. Only the keys"
                " you pass are changed. These are handed to Darts' LightGBMModel, so"
                " besides LightGBM's own parameters (e.g. 'max_depth',"
                " 'min_child_samples', 'min_data_per_group') this also reaches"
                " 'add_encoders' and 'categorical_future_covariates'. Note that 'lags',"
                " 'lags_future_covariates' and 'output_chunk_shift' are derived per"
                " forecast horizon and cannot be overridden here."
            ),
            "example": {"max_depth": 6, "min_child_samples": 10},
            "cli": {
                "option": "--model-params",
                "extra_help": "Pass as JSON, e.g. '{\"max_depth\": 6}'.",
                "cli-exclusive": True,
            },
        },
    )
    missing_threshold = fields.Float(
        data_key="missing-threshold",
        load_default=1.0,
        metadata={
            "description": "Maximum fraction of missing data allowed before raising an error. Defaults to 1.0.",
            "example": 0.1,
            "cli": {
                "option": "--missing-threshold",
                "extra_help": "Missing data under this threshold will be filled using forward filling or linear interpolation.",
            },
        },
    )
    ensure_positive = fields.Bool(
        data_key="ensure-positive",
        load_default=False,
        allow_none=True,
        metadata={
            # Meant to be deprecated in favour of the explicit `lower` bound, which says the same thing without hiding it inside the model.
            "description": "Whether to clip negative values in forecasts. Defaults to false (disabled). Prefer setting ``lower`` to 0, which bounds the forecast explicitly; this field is meant to be deprecated.",
            "example": True,
            "cli": {
                "option": "--ensure-positive",
                "extra_help": (
                    "Deprecated: set `lower` to 0 in the file passed to --config instead,"
                    " which bounds the forecast explicitly rather than inside the model."
                ),
            },
        },
    )
    lower = fields.Raw(
        required=False,
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Optional lower bound for forecast values after prediction. Unitless values are interpreted in the output sensor unit.",
            "example": "0 kW",
        },
    )
    upper = fields.Raw(
        required=False,
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Optional upper bound for forecast values after prediction. Unitless values are interpreted in the output sensor unit.",
            "example": "20 kW",
        },
    )
    snap = fields.Dict(
        keys=fields.Raw(),
        values=fields.List(fields.Raw(), validate=validate.Length(equal=2)),
        required=False,
        load_default={},
        metadata={
            "description": "Optional mapping from snap targets to [first, second] intervals. Values inside an interval are replaced by the snap target before storage. The target must lie within the interval (on a bound or inside it). The first bound is inclusive and the second exclusive, so [first, second) by default; reverse the order to close the upper side instead.",
            "example": {"0 kW": ["0 kW", "4 kW"]},
        },
    )
    train_start = AwareDateTimeOrDateField(
        data_key="train-start",
        required=False,
        allow_none=True,
        metadata={
            "description": "Timestamp marking the start of training data. Defaults to train_period before start if not set.",
            "example": "2025-01-01T00:00:00+01:00",
            "cli": {
                "cli-exclusive": True,
                "option": "--train-start",
                "aliases": ["--start-date", "--train-start"],
            },
        },
    )
    train_period = DurationField(
        data_key="train-period",
        load_default=DEFAULT_TRAIN_PERIOD,
        allow_none=True,
        metadata={
            "description": (
                "How much history to train on (ISO 8601 format, min 2 days). Defaults to P30D (30 days). "
                "Together with train-start this bounds the training window: training starts no earlier than train-start, and spans no more than train-period, so whichever of the two asks for less data decides. "
                "max-training-period said the same thing, and is still accepted as a deprecated alias."
            ),
            "example": "P7D",
            "cli": {
                "cli-exclusive": True,
                "option": "--train-period",
                "aliases": ["--max-training-period"],
            },
        },
    )
    retrain_frequency = DurationField(
        data_key="retrain-frequency",
        load_default=PlanningDurationField.load_default,
        allow_none=True,
        metadata={
            "description": "Frequency of retraining/prediction cycle (ISO 8601 duration). Defaults to prediction window length if not set.",
            "example": "PT24H",
            "cli": {
                "cli-exclusive": True,
                "option": "--retrain-frequency",
            },
        },
    )

    @pre_load
    def fold_in_max_training_period(self, data, **kwargs):
        """Read the deprecated max-training-period as the train-period it always was.

        Both said how far back training may reach, so a config carrying both asks twice,
        and the shorter of the two is all that either of them allows.
        Folding it in here keeps configs written before the two were merged working, without keeping the merged name in the schema.
        """
        if not isinstance(data, dict) or "max-training-period" not in data:
            return data
        data = dict(data)
        deprecated = data.pop("max-training-period")
        if deprecated is None:
            return data
        stated = data.get("train-period")
        if stated is None:
            data["train-period"] = deprecated
            return data
        stated_length = _fixed_length_or_none(stated)
        deprecated_length = _fixed_length_or_none(deprecated)
        if stated_length is None or deprecated_length is None:
            # One of them is malformed, or is a length that varies, such as a year.
            # Hand that one to the field, which says what is wrong with it, rather than quietly going with the other.
            data["train-period"] = stated if stated_length is None else deprecated
            return data
        data["train-period"] = (
            stated if stated_length <= deprecated_length else deprecated
        )
        return data

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):  # noqa: C901
        if data["retrain_frequency"] < timedelta(hours=1):
            raise ValidationError(
                "retrain-frequency must be at least 1 hour",
                field_name="retrain_frequency",
            )

        train_period = data.get("train_period")

        # Say this first: a Duration cannot be compared to a timedelta, so any check below it would raise a TypeError rather than report the problem.
        if isinstance(train_period, Duration):
            # DurationField only returns Duration when years/months are present
            raise ValidationError(
                "train-period must be specified using days or smaller units "
                "(e.g. P365D, PT48H). Years and months are not supported.",
                field_name="train_period",
            )

        if train_period is not None and train_period < timedelta(days=2):
            raise ValidationError(
                "train-period must be at least 2 days (48 hours)",
                field_name="train_period",
            )

    @validates_schema
    def validate_post_processing(self, data: dict, **kwargs):
        """Fail fast on unparseable post-processing values.

        Unit compatibility with the sensor and interval semantics can only be
        checked once the output sensor is known, so those run at forecast time.
        """
        errors = bound_validation_errors(
            data.get("lower"), data.get("upper"), data.get("snap")
        )
        if errors:
            raise ValidationError(errors)

    @validates_schema
    def refuse_several_entries_for_the_sensor_to_forecast(self, data: dict, **kwargs):
        """Refuse a config that describes the sensor being forecast more than once.

        Such an entry is taken out of the regressor lists and describes the target,
        so two of them are two answers to one question, whichever lists they were written in.
        Reading the last one and dropping the rest would leave a config whose recorded text does not say what the forecast did.
        The entries are counted before the lists are merged, since `regressors` asks for both roles with one entry.
        """
        written_in = [
            field_name
            for field_name in ("past_regressors", "future_regressors", "regressors")
            for entry in data.get(field_name) or []
            if isinstance(entry, AutoSensorReference)
        ]
        if len(written_in) > 1:
            spelled = ", ".join(
                sorted(snake_to_kebab(field_name) for field_name in set(written_in))
            )
            raise ValidationError(
                f"The sensor being forecast is described {len(written_in)} times, under {spelled}."
                f' Describe it once: an entry naming "{AUTO_SENSOR}" says how that sensor is read, wherever it is written,'
                " so a second one cannot say anything the first does not."
            )

    @post_load
    def resolve_config(self, data: dict, **kwargs) -> dict:  # noqa: C901

        future_regressors = data.get("future_regressors", [])
        past_regressors = data.get("past_regressors", [])
        past_and_future_regressors = data.pop("regressors", [])

        if past_and_future_regressors:
            future_regressors = future_regressors + [
                regressor
                for regressor in past_and_future_regressors
                if regressor not in future_regressors
            ]
            past_regressors = past_regressors + [
                regressor
                for regressor in past_and_future_regressors
                if regressor not in past_regressors
            ]

        data["future_regressors"] = future_regressors
        data["past_regressors"] = past_regressors

        # A null train-period asks for no limit of its own, which leaves the default to say how much history to use.
        train_period = data.get("train_period") or DEFAULT_TRAIN_PERIOD
        data["train_period_in_hours"] = train_period // timedelta(hours=1)
        return data


DEFAULT_INSTANTANEOUS_FORECAST_RESOLUTION = timedelta(hours=1)


def _forecast_resolution(
    sensor: Sensor | SensorReference,
    resolution: timedelta | Duration | None,
    data_until: datetime | None = None,
) -> tuple[timedelta | None, str | None]:
    """Return the resolution to forecast a sensor at, and where it came from if it was not given.

    An instantaneous sensor has no resolution of its own to step through time by.
    Unless one is given, it is derived, as described in ``_derive_instantaneous_resolution``.
    Any other sensor is forecast at its own resolution, so a different one is refused rather than ignored.

    :param sensor:      The sensor to forecast, or a source-filtered reference to it.
    :param resolution:  The resolution given in the parameters, if any.
    :param data_until:  End of the period whose data may be used to derive a resolution for an instantaneous sensor.
                        Without it, no resolution is derived, and None is returned for an instantaneous sensor without a given resolution.
    :returns:           The resolution, and a description of its origin when it was derived (None when it was given, or is the sensor's own).
    :raises ValidationError: If an instantaneous sensor gets a resolution that is not positive, or another sensor gets a different one.
    """
    sensor_resolution = sensor.event_resolution
    if sensor_resolution == timedelta(0):
        if resolution is None:
            if data_until is None:
                return None, None
            return _derive_instantaneous_resolution(sensor, data_until)
        # A duration in months or years parses to a Duration, which has no fixed length to step by.
        if not isinstance(resolution, timedelta) or resolution <= timedelta(0):
            raise ValidationError(
                "The resolution to forecast at must be a positive duration of fixed length, such as 'PT1H' rather than 'P1M'.",
                field_name="resolution",
            )
        return resolution, None
    if resolution is not None and resolution != sensor_resolution:
        raise ValidationError(
            f"This sensor is forecast at its own resolution ({sensor_resolution}); a resolution can only be set for an instantaneous sensor.",
            field_name="resolution",
        )
    return sensor_resolution, None


def _derive_instantaneous_resolution(
    sensor: Sensor | SensorReference, data_until: datetime
) -> tuple[timedelta, str]:
    """Derive the resolution to forecast an instantaneous sensor at, when none is given.

    In order of precedence:

    1. The sensor's ``frequency`` attribute, which also rounds the timing of its incoming readings.
    2. The most common duration between the sensor's readings in the default training period before ``data_until``,
       snapped to whole minutes (at least one minute), so that slightly irregular timing does not yield an odd resolution.
    3. One hour.

    :param sensor:      The instantaneous sensor, or a source-filtered reference to it.
    :param data_until:  End of the period whose readings are used to infer the resolution.
    :returns:           The resolution, and a description of where it came from.
    :raises ValidationError: If the sensor's ``frequency`` attribute is not a positive duration.
    """
    if isinstance(sensor, SensorReference):
        sensor = sensor.sensor
    frequency = sensor.get_attribute("frequency")
    if frequency:
        try:
            resolution = pd.Timedelta(pd.tseries.frequencies.to_offset(frequency))
        except (ValueError, TypeError):
            resolution = None
        if resolution is None or pd.isna(resolution) or resolution <= timedelta(0):
            raise ValidationError(
                f"The sensor's 'frequency' attribute ({frequency!r}) is not a positive duration, such as '15min', so it cannot set the resolution to forecast at; set 'resolution' instead.",
                field_name="resolution",
            )
        return (
            resolution.to_pytimedelta(),
            "taken from the sensor's 'frequency' attribute",
        )

    bdf = sensor.search_beliefs(
        event_starts_after=data_until - DEFAULT_TRAIN_PERIOD,
        event_ends_before=data_until,
        most_recent_beliefs_only=True,
        one_deterministic_belief_per_event=True,
    )
    event_starts = pd.DatetimeIndex(bdf.event_starts.unique()).sort_values()
    if len(event_starts) >= 2:
        # As when inferring the resolution of posted data: two events only have their difference to go by.
        frequency = (
            event_starts[1] - event_starts[0]
            if len(event_starts) == 2
            else bdf.most_common_event_frequency
        )
        minutes = max(1, round(pd.Timedelta(frequency) / pd.Timedelta(minutes=1)))
        resolution = timedelta(minutes=minutes)
        logging.info(
            f"Forecasting instantaneous sensor {sensor.id} at a resolution of {resolution}, inferred from its data."
        )
        return resolution, "inferred from the sensor's data"
    return (
        DEFAULT_INSTANTANEOUS_FORECAST_RESOLUTION,
        "the default for an instantaneous sensor without data to infer one from",
    )


class ForecasterParametersSchema(Schema):
    """
    NB cli-exclusive fields are not exposed via the API (removed by make_openapi_compatible).
    """

    sensor = SensorIdOrReferenceField(
        data_key="sensor",
        required=True,
        metadata={
            "description": (
                "ID of the sensor to forecast."
                " Which of the sources recording on it hold the truth to train on, and how to clean its readings, is said in the forecaster's config,"
                " by an entry naming 'auto' among the regressors."
                " Without such an entry, every source on the sensor is trained on, except forecasters,"
                " which are left out so that the forecaster does not learn from its own forecasts."
            ),
            "example": 2092,
            "cli": {
                "option": "--sensor",
                "extra_help": "Pass the ID of the sensor to forecast.",
            },
        },
    )
    model_save_dir = fields.Str(
        data_key="model-save-dir",
        allow_none=True,
        load_default="flexmeasures/data/models/forecasting/artifacts/models",
        metadata={
            "description": "Directory to save the trained model.",
            "example": "flexmeasures/data/models/forecasting/artifacts/models",
            "cli": {
                "cli-exclusive": True,
                "option": "--model-save-dir",
            },
        },
    )
    output_path = fields.Str(
        data_key="output-path",
        required=False,
        allow_none=True,
        metadata={
            "description": "Directory to save prediction outputs. Defaults to None (no outputs saved).",
            "example": "flexmeasures/data/models/forecasting/artifacts/forecasts",
            "cli": {
                "cli-exclusive": True,
                "option": "--output-path",
            },
        },
    )
    start = AwareDateTimeOrDateField(
        data_key="start",
        required=False,
        allow_none=True,
        metadata={
            "description": "Start date for predictions. Defaults to now, floored to the sensor resolution, so that the first forecast is about the ongoing event.",
            "example": "2025-01-08T00:00:00+01:00",
            "cli": {
                "option": "--start",
                "aliases": ["--start-predict-date", "--from-date"],
            },
        },
    )
    end = AwareDateTimeOrDateField(
        data_key="end",
        required=False,
        allow_none=True,
        inclusive=True,
        metadata={
            "description": "End of the last event forecasted. Use either this field or the duration field.",
            "example": "2025-10-15T00:00:00+01:00",
            "cli": {
                "cli-exclusive": True,
                "option": "--end",
                "aliases": ["--end-date", "--to-date"],
            },
        },
    )
    duration = PlanningDurationField(
        load_default=PlanningDurationField.load_default,
        metadata=dict(
            description="The duration for which to create the forecast, in ISO 8601 duration format. Defaults to the planning horizon.",
            example="PT24H",
            cli={
                "option": "--duration",
                "aliases": ["--predict-period"],
            },
        ),
    )
    belief_time = AwareDateTimeField(
        format="iso",
        data_key="prior",
        metadata={
            "description": "The forecaster is only allowed to take into account sensor data that has been recorded prior to this [belief time](https://flexmeasures.readthedocs.io/latest/concepts/time-series-and-beliefs.html#beliefs-and-their-recording-time). "
            "By default, the most recent sensor data is used. This field is especially useful for running simulations.",
            "example": "2026-01-15T10:00+01:00",
            "cli": {
                "option": "--prior",
            },
        },
    )
    max_forecast_horizon = DurationField(
        data_key="max-forecast-horizon",
        required=False,
        allow_none=True,
        metadata={
            "description": "Maximum forecast horizon. Defaults to covering the whole prediction period (which itself defaults to 48 hours).",
            "example": "PT48H",
            "cli": {
                "cli-exclusive": True,
                "option": "--max-forecast-horizon",
            },
        },
    )
    forecast_frequency = DurationField(
        data_key="forecast-frequency",
        required=False,
        allow_none=True,
        metadata={
            "description": "How often to recompute forecasts. This setting can be used to get forecasts from multiple viewpoints, which is especially useful for running simulations. Defaults to the max-forecast-horizon.",
            "example": "PT1H",
            "cli": {
                "option": "--forecast-frequency",
            },
        },
    )
    resolution = DurationField(
        data_key="resolution",
        required=False,
        allow_none=True,
        metadata={
            "description": (
                "Resolution to forecast at, in ISO 8601 duration format."
                " Only used for an instantaneous sensor (one with a zero resolution), for which it is the frequency of the forecasts,"
                " as for the resolution of a data request (see 'Frequency and resolution' in the documentation):"
                " its readings are taken onto slots of this resolution, and its forecasts are saved as instantaneous values at the start of each slot."
                " If not given, it is the sensor's 'frequency' attribute,"
                " or else the most common duration between the sensor's readings in the 30 days before the predictions start, in whole minutes,"
                " or else one hour."
                " Any other sensor is forecast at its own resolution, so a different one is refused."
            ),
            "example": "PT1H",
            "cli": {
                "option": "--resolution",
            },
        },
    )
    probabilistic = fields.Bool(
        data_key="probabilistic",
        load_default=False,
        metadata={
            "description": "Enable probabilistic predictions if True. Defaults to false.",
            "example": False,
            "cli": {
                "cli-exclusive": True,
                "option": "--probabilistic",
            },
        },
    )
    sensor_to_save = SensorIdField(
        data_key="sensor-to-save",
        required=False,
        allow_none=True,
        metadata={
            "description": "Sensor ID where forecasts will be saved; defaults to target sensor.",
            "example": 2092,
            "cli": {
                "option": "--sensor-to-save",
            },
        },
    )
    dry_run = fields.Bool(
        data_key="dry-run",
        load_default=False,
        metadata={
            "description": "Add this flag to avoid saving the results to the database.",
            "cli": {
                "cli-exclusive": True,
                "is_flag": True,
                "option": "--dry-run",
            },
        },
    )

    @pre_load
    def sanitize_input(self, data, **kwargs):

        # Check predict period
        if len({"start", "end", "duration"} & data.keys()) > 2:
            raise ValidationError(
                "Provide 'duration' with either 'start' or 'end', but not with both.",
                field_name="duration",
            )

        # Drop None values
        data = {k: v for k, v in data.items() if v is not None}

        return data

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):  # noqa: C901
        end_date = data.get("end")
        predict_start = data.get("start", None)
        sensor = data.get("sensor")

        # todo: consider moving this to the run method in train_predict.py
        # if train_start is not None and end is not None and train_start >= end_date:
        #     raise ValidationError(
        #         "train_start must be before end", field_name="train-start"
        #     )

        if predict_start:
            # if train_start is not None and predict_start < train_start:
            #     raise ValidationError(
            #         "start cannot be before start",
            #         field_name="start",
            #     )
            if end_date is not None and predict_start >= end_date:
                raise ValidationError(
                    "start must be before end",
                    field_name="start",
                )

        # A given resolution is checked here, while the timing it must divide is checked once it is resolved, see resolve_config.
        _forecast_resolution(sensor, data.get("resolution"))

    @post_load(pass_original=True)
    def resolve_config(  # noqa: C901
        self, data: dict, original_data: dict | None = None, **kwargs
    ) -> dict:
        """Resolve timing parameters, using sensible defaults and choices.

        Defaults:
        1. predict-period defaults to minimum of (FM planning horizon and max-forecast-horizon) only if there is a single default viewpoint.
        2. max-forecast-horizon defaults to the predict-period
        3. forecast-frequency defaults to minimum of (FM planning horizon, predict-period, max-forecast-horizon)

        Choices:
        1. If max-forecast-horizon < predict-period, we raise a ValidationError due to incomplete coverage
        2. retraining-frequency becomes the maximum of (FM planning horizon and forecast-frequency, this is capped by the predict-period.
        """

        target_sensor = data["sensor"]

        now = server_now()
        resolution, origin = _forecast_resolution(
            target_sensor, data.get("resolution"), data_until=data.get("start", now)
        )
        # Say where a derived resolution came from, and how to choose another, when the timing does not fit it.
        origin_note = (
            f", {origin}; set 'resolution' to forecast at another one" if origin else ""
        )
        for field_name, duration in (
            ("max-forecast-horizon", data.get("max_forecast_horizon")),
            ("forecast-frequency", data.get("forecast_frequency")),
        ):
            if duration is not None and duration % resolution != timedelta(0):
                raise ValidationError(
                    f"{field_name} must be a multiple of the forecast resolution ({resolution}{origin_note})"
                )
        floored_now = floor_to_resolution(now, resolution)

        if data.get("start") is None:
            if original_data.get("duration") and data.get("end") is not None:
                predict_start = data["end"] - data["duration"]
            else:
                predict_start = floored_now
                # Validate that the resolved predict_start is before the explicit end.
                # Note: predict_start == end is also rejected because a zero-duration window
                # causes ZeroDivisionError at `m_viewpoints = max(predict_period // forecast_frequency, 1)`.
                end = data.get("end")
                if end is not None and predict_start >= end:
                    raise ValidationError(
                        f"Resolved predict start ({predict_start.isoformat()}) is not before end ({end.isoformat()})."
                        " Provide --start explicitly or choose a later --end.",
                        field_name="end",
                    )
        else:
            predict_start = data["start"]

        save_belief_time = data.get(
            "belief_time",
            now if data.get("start") is None else predict_start,
        )

        if data.get("end") is None:
            data["end"] = predict_start + data["duration"]

        predict_period = (
            data["end"] - predict_start if data.get("end") else data["duration"]
        )
        forecast_frequency = data.get("forecast_frequency")

        max_forecast_horizon = data.get("max_forecast_horizon")

        # Check for inconsistent parameters explicitly set
        if (
            "max-forecast-horizon" in original_data
            and "duration" in original_data
            and max_forecast_horizon < predict_period
        ):
            raise ValidationError(
                "This combination of parameters will not yield forecasts for the entire prediction window.",
                field_name="max_forecast_horizon",
            )

        if max_forecast_horizon is None:
            max_forecast_horizon = predict_period
        elif max_forecast_horizon > predict_period:
            raise ValidationError(
                "max-forecast-horizon must be less than or equal to predict-period",
                field_name="max_forecast_horizon",
            )
        elif max_forecast_horizon < predict_period and forecast_frequency is None:
            # Update the default predict-period if the user explicitly set a smaller max-forecast-horizon,
            # unless they also set a forecast-frequency explicitly
            predict_period = max_forecast_horizon

        if forecast_frequency is None:
            forecast_frequency = min(
                max_forecast_horizon,
                predict_period,
            )

        predict_period_in_hours = int(predict_period.total_seconds() / 3600)

        if data.get("sensor_to_save") is None:
            # Forecasts are recorded on a sensor, never on a source-filtered view of one,
            # so a referenced target contributes only the sensor it wraps.
            sensor_to_save = (
                target_sensor.sensor
                if isinstance(target_sensor, SensorReference)
                else target_sensor
            )
        else:
            sensor_to_save = data["sensor_to_save"]

        output_path = data.get("output_path")
        if output_path and not os.path.exists(output_path):
            os.makedirs(output_path)

        model_save_dir = data.get("model_save_dir")
        if model_save_dir is None:
            # Read default from schema
            model_save_dir = self.fields["model_save_dir"].load_default

        m_viewpoints = max(predict_period // forecast_frequency, 1)

        result = dict(
            sensor=target_sensor,
            model_save_dir=model_save_dir,
            output_path=output_path,
            end_date=data["end"],
            predict_start=predict_start,
            predict_period_in_hours=predict_period_in_hours,
            max_forecast_horizon=max_forecast_horizon,
            forecast_frequency=forecast_frequency,
            probabilistic=data.get("probabilistic"),
            sensor_to_save=sensor_to_save,
            save_belief_time=save_belief_time,
            beliefs_before=data.get("belief_time"),
            m_viewpoints=m_viewpoints,
            dry_run=data.get("dry_run", False),
            resolution=resolution,
        )
        if "config" in data:
            result["config"] = data["config"]
        return result


class ForecastingTriggerSchema(ForecasterParametersSchema):

    config = fields.Nested(
        TrainPredictPipelineConfigSchema(),
        required=False,
        load_default={},
        metadata={
            "description": "Changing any of these will result in a new data source ID."
        },
    )
