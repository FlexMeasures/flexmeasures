from __future__ import annotations

import logging
import os

from datetime import timedelta
from isodate.duration import Duration

from marshmallow import (
    fields,
    Schema,
    validates_schema,
    pre_load,
    post_load,
    ValidationError,
)

from flexmeasures.data.schemas import SensorIdField
from flexmeasures.data.schemas.times import (
    AwareDateTimeField,
    AwareDateTimeOrDateField,
    DurationField,
    PlanningDurationField,
)
from flexmeasures.data.models.forecasting.utils import floor_to_resolution
from flexmeasures.utils.time_utils import server_now


class TrainPredictPipelineConfigSchema(Schema):

    model = fields.String(load_default="CustomLGBM")
    future_regressors = fields.List(
        SensorIdField(),
        data_key="future-regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs to be treated only as future regressors."
                " Use this if only forecasts recorded on this sensor matter as a regressor."
            ),
            "example": [2093, 2094],
            "cli": {
                "option": "--future-regressors",
            },
        },
    )
    past_regressors = fields.List(
        SensorIdField(),
        data_key="past-regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs to be treated only as past regressors."
                " Use this if only realizations recorded on this sensor matter as a regressor."
            ),
            "example": [2095],
            "cli": {
                "option": "--past-regressors",
            },
        },
    )
    regressors = fields.List(
        SensorIdField(),
        data_key="regressors",
        load_default=[],
        metadata={
            "description": (
                "Sensor IDs used as both past and future regressors."
                " Use this if both realizations and forecasts recorded on this sensor matter as a regressor."
            ),
            "example": [2093, 2094, 2095],
            "cli": {
                "option": "--regressors",
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
            "description": "Whether to clip negative values in forecasts. Defaults to None (disabled).",
            "example": True,
            "cli": {
                "option": "--ensure-positive",
            },
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
        load_default=timedelta(days=30),
        allow_none=True,
        metadata={
            "description": "Duration of the initial training period (ISO 8601 format, min 2 days). If not set, derived from train_start and start if not set or defaults to P30D (30 days).",
            "example": "P7D",
            "cli": {
                "cli-exclusive": True,
                "option": "--train-period",
            },
        },
    )
    max_training_period = DurationField(
        data_key="max-training-period",
        load_default=timedelta(days=365),
        allow_none=True,
        metadata={
            "description": "Maximum duration of the training period. Defaults to 1 year (P1Y).",
            "example": "P1Y",
            "cli": {
                "cli-exclusive": True,
                "option": "--max-training-period",
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

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):  # noqa: C901
        if data["retrain_frequency"] < timedelta(hours=1):
            raise ValidationError(
                "retrain-frequency must be at least 1 hour",
                field_name="retrain_frequency",
            )

        train_period = data.get("train_period")
        max_training_period = data.get("max_training_period")

        if train_period is not None and train_period < timedelta(days=2):
            raise ValidationError(
                "train-period must be at least 2 days (48 hours)",
                field_name="train_period",
            )

        if isinstance(max_training_period, Duration):
            # DurationField only returns Duration when years/months are present
            raise ValidationError(
                "max-training-period must be specified using days or smaller units "
                "(e.g. P365D, PT48H). Years and months are not supported.",
                field_name="max_training_period",
            )

    @post_load
    def resolve_config(self, data: dict, **kwargs) -> dict:  # noqa: C901

        future_regressors = data.get("future_regressors", [])
        past_regressors = data.get("past_regressors", [])
        past_and_future_regressors = data.pop("regressors", [])

        if past_and_future_regressors:
            future_regressors = list(
                set(future_regressors + past_and_future_regressors)
            )
            past_regressors = list(set(past_regressors + past_and_future_regressors))

        data["future_regressors"] = future_regressors
        data["past_regressors"] = past_regressors

        train_period_in_hours = data["train_period"] // timedelta(hours=1)
        max_training_period = data["max_training_period"]
        if train_period_in_hours > max_training_period // timedelta(hours=1):
            train_period_in_hours = max_training_period // timedelta(hours=1)
            logging.warning(
                f"train-period is greater than max-training-period ({max_training_period}), setting train-period to max-training-period",
            )

        data["train_period_in_hours"] = train_period_in_hours
        return data


class ForecasterParametersSchema(Schema):
    """
    NB cli-exclusive fields are not exposed via the API (removed by make_openapi_compatible).
    """

    sensor = SensorIdField(
        data_key="sensor",
        required=True,
        metadata={
            "description": "ID of the sensor to forecast.",
            "example": 2092,
            "cli": {
                "option": "--sensor",
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
    belief_time = AwareDateTimeField(
        format="iso",
        data_key="prior",
        metadata={
            "description": "The forecaster is only allowed to take into account sensor data that has been recorded prior to this [belief time](https://flexmeasures.readthedocs.io/latest/api/notation.html#tracking-the-recording-time-of-beliefs). "
            "By default, the most recent sensor data is used. This field is especially useful for running simulations.",
            "example": "2026-01-15T10:00+01:00",
            "cli": {
                "option": "--prior",
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
        max_forecast_horizon = data.get("max_forecast_horizon")
        forecast_frequency = data.get("forecast_frequency")
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

        if max_forecast_horizon is not None:
            if max_forecast_horizon % sensor.event_resolution != timedelta(0):
                raise ValidationError(
                    f"max-forecast-horizon must be a multiple of the sensor resolution ({sensor.event_resolution})"
                )

        if forecast_frequency is not None:
            if forecast_frequency % sensor.event_resolution != timedelta(0):
                raise ValidationError(
                    f"forecast-frequency must be a multiple of the sensor resolution ({sensor.event_resolution})"
                )

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

        resolution = target_sensor.event_resolution

        now = server_now()
        floored_now = floor_to_resolution(now, resolution)

        if data.get("start") is None:
            if original_data.get("duration") and data.get("end") is not None:
                predict_start = data["end"] - data["duration"]
            else:
                predict_start = floored_now
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
            sensor_to_save = target_sensor
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

        return dict(
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
            m_viewpoints=m_viewpoints,
        )


class ForecastingTriggerSchema(ForecasterParametersSchema):

    config = fields.Nested(
        TrainPredictPipelineConfigSchema(),
        required=False,
        metadata={
            "description": "Changing any of these will result in a new data source ID."
        },
    )
