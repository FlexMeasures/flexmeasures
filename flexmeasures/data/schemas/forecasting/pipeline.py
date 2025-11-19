from __future__ import annotations

import logging
import os

from datetime import timedelta

from marshmallow import fields, Schema, validates_schema, post_load, ValidationError

from flexmeasures.data.schemas import SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeOrDateField, DurationField
from flexmeasures.data.models.forecasting.utils import floor_to_resolution
from flexmeasures.utils.time_utils import server_now


class TrainPredictPipelineConfigSchema(Schema):

    model = fields.String(load_default="CustomLGBM")


class ForecasterParametersSchema(Schema):

    sensor = SensorIdField(
        required=True,
        metadata={
            "description": "ID of the sensor to forecast.",
            "example": 2092,
        },
    )
    future_regressors = fields.List(
        SensorIdField(),
        required=False,
        metadata={
            "description": "Sensor IDs to be treated only as future regressors (sensors only containing forecasts).",
            "example": [2093, 2094],
        },
    )
    past_regressors = fields.List(
        SensorIdField(),
        required=False,
        metadata={
            "description": "Sensor IDs to be treated only as past regressors (sensors only containing realized measurements).",
            "example": [2095],
        },
    )
    regressors = fields.List(
        SensorIdField(),
        required=False,
        metadata={
            "description": "Sensor IDs used as both past and future regressors (sensors containing both forecasts and realized measurements).",
            "example": [2093, 2094, 2095],
        },
    )
    model_save_dir = fields.Str(
        required=True,
        metadata={
            "description": "Directory to save the trained model.",
            "example": "flexmeasures/data/models/forecasting/artifacts/models",
        },
    )
    output_path = fields.Str(
        required=False,
        allow_none=True,
        metadata={
            "description": "Directory to save prediction outputs.",
            "example": "flexmeasures/data/models/forecasting/artifacts/forecasts",
        },
    )
    start_date = AwareDateTimeOrDateField(
        required=False,
        allow_none=True,
        metadata={
            "description": "Timestamp marking the start of training data.",
            "example": "2025-01-01T00:00:00+01:00",
        },
    )
    end_date = AwareDateTimeOrDateField(
        required=True,
        inclusive=True,
        metadata={
            "description": "End date for running the pipeline.",
            "example": "2025-10-15T00:00:00+01:00",
        },
    )
    train_period = DurationField(
        required=False,
        allow_none=True,
        metadata={
            "description": "Duration of the initial training period (ISO 8601 format, min 2 days).",
            "example": "P7D",
        },
    )
    start_predict_date = AwareDateTimeOrDateField(
        required=False,
        allow_none=True,
        metadata={
            "description": "Start date for predictions.",
            "example": "2025-01-08T00:00:00+01:00",
        },
    )
    retrain_frequency = DurationField(
        required=False,
        allow_none=True,
        metadata={
            "description": "Frequency of retraining/prediction cycle (ISO 8601 duration).",
            "example": "PT24H",
        },
    )  # aka the predict period
    max_forecast_horizon = DurationField(
        required=False,
        allow_none=True,
        load_default=timedelta(hours=48),
        metadata={
            "description": "Maximum forecast horizon.",
            "example": "PT48H",
        },
    )
    forecast_frequency = DurationField(
        required=False,
        allow_none=True,
        load_default=timedelta(hours=1),
        metadata={
            "description": "How often to recompute forecasts.",
            "example": "PT1H",
        },
    )
    probabilistic = fields.Bool(
        required=True,
        metadata={
            "description": "Enable probabilistic predictions if True.",
            "example": False,
        },
    )
    sensor_to_save = SensorIdField(
        required=False,
        allow_none=True,
        metadata={
            "description": "Sensor ID where forecasts will be saved; defaults to target sensor.",
            "example": 2092,
        },
    )
    ensure_positive = fields.Bool(required=False, allow_none=True)
    missing_threshold = fields.Float(required=False, load_default=1.0)
    as_job = fields.Bool(
        load_default=False,
        metadata={
            "description": "If True, forecast using RQ jobs in the background (needs a worker assigned to the forecasting queue)."
        },
    )
    max_training_period = DurationField(required=False, allow_none=True)

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):
        start_date = data["start_date"]
        end_date = data["end_date"]
        predict_start = data.get("start_predict_date", None)
        train_period = data.get("train_period")
        retrain_frequency = data.get("retrain_frequency")
        max_forecast_horizon = data.get("max_forecast_horizon")
        forecast_frequency = data.get("forecast_frequency")
        sensor = data.get("sensor")

        if start_date >= end_date:
            raise ValidationError(
                "start-date must be before end-date", field_name="start_date"
            )

        if predict_start:
            if predict_start < start_date:
                raise ValidationError(
                    "start-predict-date cannot be before start-date",
                    field_name="start_predict_date",
                )
            if predict_start >= end_date:
                raise ValidationError(
                    "start-predict-date must be before end-date",
                    field_name="start_predict_date",
                )

        if train_period is not None and train_period < timedelta(days=2):
            raise ValidationError(
                "train-period must be at least 2 days (48 hours)",
                field_name="train_period",
            )

        if retrain_frequency is not None and retrain_frequency <= timedelta(0):
            raise ValidationError(
                "retrain-frequency must be greater than 0",
                field_name="retrain_frequency",
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

    @post_load
    def resolve_config(self, data: dict, **kwargs) -> dict:  # noqa: C901

        target_sensor = data["sensor"]

        future_regressors = data.get("future_regressors", [])
        past_regressors = data.get("past_regressors", [])
        past_and_future_regressors = data.get("regressors", [])

        if past_and_future_regressors:
            future_regressors = list(
                set(future_regressors + past_and_future_regressors)
            )
            past_regressors = list(set(past_regressors + past_and_future_regressors))

        resolution = target_sensor.event_resolution

        predict_start = data.get("start_predict_date") or floor_to_resolution(
            server_now(), resolution
        )
        if data.get("start_predict_date") is None and data.get("train_period"):

            predict_start = data["start_date"] + data["train_period"]

        if data.get("train_period") is None and data["start_date"] is None:
            train_period_in_hours = 30 * 24  # Set default train_period value to 30 days

        elif data.get("train_period") is None and data["start_date"]:
            train_period_in_hours = int(
                (predict_start - data["start_date"]).total_seconds() / 3600
            )
        else:
            train_period_in_hours = data["train_period"] // timedelta(hours=1)

        if train_period_in_hours < 48:
            raise ValidationError(
                "train-period must be at least 2 days (48 hours)",
                field_name="train_period",
            )
        max_training_period = data.get("max_training_period") or timedelta(days=365)
        if train_period_in_hours > max_training_period // timedelta(hours=1):
            train_period_in_hours = max_training_period // timedelta(hours=1)
            logging.warning(
                f"train-period is greater than max-training-period ({max_training_period}), setting train-period to max-training-period",
            )

        if data.get("retrain_frequency") is None:
            retrain_frequency_in_hours = int(
                (data["end_date"] - predict_start).total_seconds() / 3600
            )
        else:
            retrain_frequency_in_hours = data["retrain_frequency"] // timedelta(hours=1)
            if retrain_frequency_in_hours < 1:
                raise ValidationError("retrain-frequency must be at least 1 hour")

        if data["start_date"] is None:
            start_date = predict_start - timedelta(hours=train_period_in_hours)
        else:
            start_date = data["start_date"]

        max_forecast_horizon = data.get("max_forecast_horizon")
        forecast_frequency = data.get("forecast_frequency")

        if max_forecast_horizon is None and forecast_frequency is None:
            max_forecast_horizon = timedelta(hours=retrain_frequency_in_hours)
            forecast_frequency = timedelta(hours=retrain_frequency_in_hours)
        elif max_forecast_horizon is None:
            max_forecast_horizon = forecast_frequency
        elif forecast_frequency is None:
            forecast_frequency = max_forecast_horizon

        if data.get("sensor_to_save") is None:
            sensor_to_save = target_sensor
        else:
            sensor_to_save = data["sensor_to_save"]

        output_path = data.get("output_path")
        if output_path and not os.path.exists(output_path):
            os.makedirs(output_path)

        ensure_positive = data.get("ensure_positive")

        return dict(
            future_regressors=future_regressors,
            past_regressors=past_regressors,
            target=target_sensor,
            model_save_dir=data["model_save_dir"],
            output_path=output_path,
            start_date=start_date,
            end_date=data["end_date"],
            train_period_in_hours=train_period_in_hours,
            predict_start=predict_start,
            predict_period_in_hours=retrain_frequency_in_hours,
            max_forecast_horizon=max_forecast_horizon,
            forecast_frequency=forecast_frequency,
            probabilistic=data["probabilistic"],
            sensor_to_save=sensor_to_save,
            ensure_positive=ensure_positive,
            missing_threshold=data.get("missing_threshold"),
            as_job=data.get("as_job"),
        )
