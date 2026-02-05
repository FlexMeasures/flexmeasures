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
from flexmeasures.data.schemas.times import AwareDateTimeOrDateField, DurationField
from flexmeasures.data.models.forecasting.utils import floor_to_resolution
from flexmeasures.utils.time_utils import server_now


class TrainPredictPipelineConfigSchema(Schema):

    model = fields.String(load_default="CustomLGBM")


class ForecasterParametersSchema(Schema):

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
    future_regressors = fields.List(
        SensorIdField(),
        data_key="future-regressors",
        required=False,
        metadata={
            "description": (
                "Sensor IDs to be treated only as future regressors."
                "Use this if only forecasts recorded on this sensor matter as a regressor."
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
        required=False,
        metadata={
            "description": (
                "Sensor IDs to be treated only as past regressors"
                "Use this if only realizations recorded on this sensor matter as a regressor."
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
        required=False,
        metadata={
            "description": (
                "Sensor IDs used as both past and future regressors."
                "Use this if both realizations and forecasts recorded on this sensor "
            ),
            "example": [2093, 2094, 2095],
            "cli": {
                "option": "--regressors",
            },
        },
    )
    model_save_dir = fields.Str(
        data_key="model-save-dir",
        required=False,
        allow_none=True,
        load_default="flexmeasures/data/models/forecasting/artifacts/models",
        metadata={
            "description": "Directory to save the trained model.",
            "example": "flexmeasures/data/models/forecasting/artifacts/models",
            "cli": {
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
                "option": "--output-path",
            },
        },
    )
    start_date = AwareDateTimeOrDateField(
        data_key="start-date",
        required=False,
        allow_none=True,
        metadata={
            "description": "Timestamp marking the start of training data. Defaults to train_period before start_predict_date if not set.",
            "example": "2025-01-01T00:00:00+01:00",
            "cli": {
                "option": "--start-date",
                "aliases": ["--train-start"],
            },
        },
    )
    end_date = AwareDateTimeOrDateField(
        data_key="end-date",
        required=False,
        allow_none=True,
        inclusive=True,
        metadata={
            "description": "End date for running the pipeline.",
            "example": "2025-10-15T00:00:00+01:00",
            "cli": {
                "option": "--end-date",
                "aliases": ["--to-date"],

            },
        },
    )
    train_period = DurationField(
        data_key="train-period",
        required=False,
        allow_none=True,
        metadata={
            "description": "Duration of the initial training period (ISO 8601 format, min 2 days). If not set, derived from start_date and start_predict_date or defaults to P30D (30 days).",
            "example": "P7D",
            "cli": {
                "option": "--train-period",
            }
        },
    )
    start_predict_date = AwareDateTimeOrDateField(
        data_key="start-predict-date",
        required=False,
        allow_none=True,
        metadata={
            "description": "Start date for predictions. Defaults to now, floored to the sensor resolution, so that the first forecast is about the ongoing event.",
            "example": "2025-01-08T00:00:00+01:00",
            "cli": {
                "option": "--start-predict-date",
                "aliases": ["--from-date"],
            },
        },
    )
    retrain_frequency = DurationField(
        data_key="retrain-frequency",
        required=False,
        allow_none=True,
        metadata={
            "description": "Frequency of retraining/prediction cycle (ISO 8601 duration). Defaults to prediction window length if not set.",
            "example": "PT24H",
            "cli": {
                "option": "--retrain-frequency",
            }
        },
    )
    max_forecast_horizon = DurationField(
        data_key="max-forecast-horizon",
        required=False,
        allow_none=True,
        load_default=timedelta(hours=48),
        metadata={
            "description": "Maximum forecast horizon. Defaults to 'PT48H' if not set.",
            "example": "PT48H",
            "cli": {
                "option": "--max-forecast-horizon",
            },
        },
    )
    forecast_frequency = DurationField(
        data_key="forecast-frequency",
        required=False,
        allow_none=True,
        load_default=timedelta(hours=1),
        metadata={
            "description": "How often to recompute forecasts. Defaults to 1 hour.",
            "example": "PT1H",
            "cli": {
                "option": "--forecast-frequency",
            }
        },
    )
    probabilistic = fields.Bool(
        data_key="probabilistic",
        required=False,
        load_default=False,
        metadata={
            "description": "Enable probabilistic predictions if True. Defaults to false.",
            "example": False,
            "cli": {
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
    ensure_positive = fields.Bool(
        data_key="ensure-positive",
        required=False,
        allow_none=True,
        metadata={
            "description": "Whether to clip negative values in forecasts. Defaults to None (disabled).",
            "example": True,
            "cli": {
                "option": "--ensure-positive",
            },
        },
    )
    missing_threshold = fields.Float(
        data_key="missing-threshold",
        required=False,
        load_default=1.0,
        metadata={
            "description": "Maximum fraction of missing data allowed before raising an error. Defaults to 1.0.",
            "example": 0.1,
            "cli": {
                "option": "--missing-threshold",
            }
        },
    )
    as_job = fields.Bool(
        data_key="as-job",
        load_default=False,
        metadata={
            "description": "If True, compute forecasts asynchronously using RQ jobs. Defaults to False.",
            "example": True,
            "cli": {
                "option": "--as-job",
            }
        },
    )
    max_training_period = DurationField(
        data_key="max-training-period",
        required=False,
        allow_none=True,
        metadata={
            "description": "Maximum duration of the training period. Defaults to 1 year (P1Y).",
            "example": "P1Y",
            "cli": {
                "option": "--max-training-period",
            },
        },
    )

    @pre_load
    def drop_none_values(self, data, **kwargs):
        return {k: v for k, v in data.items() if v is not None}

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        predict_start = data.get("start_predict_date", None)
        train_period = data.get("train_period")
        retrain_frequency = data.get("retrain_frequency")
        max_forecast_horizon = data.get("max_forecast_horizon")
        forecast_frequency = data.get("forecast_frequency")
        sensor = data.get("sensor")
        max_training_period = data.get("max_training_period")

        if start_date is not None and end_date is not None and start_date >= end_date:
            raise ValidationError(
                "start-date must be before end-date", field_name="start_date"
            )

        if predict_start:
            if start_date is not None and predict_start < start_date:
                raise ValidationError(
                    "start-predict-date cannot be before start-date",
                    field_name="start_predict_date",
                )
            if end_date is not None and predict_start >= end_date:
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

        if isinstance(max_training_period, Duration):
            # DurationField only returns Duration when years/months are present
            raise ValidationError(
                "max-training-period must be specified using days or smaller units "
                "(e.g. P365D, PT48H). Years and months are not supported.",
                field_name="max_training_period",
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

        now = server_now()
        floored_now = floor_to_resolution(now, resolution)

        predict_start = data.get("start_predict_date") or floored_now
        save_belief_time = (
            now if data.get("start_predict_date") is None else predict_start
        )

        if (
            data.get("start_predict_date") is None
            and data.get("train_period")
            and data.get("start_date")
        ):

            predict_start = data["start_date"] + data["train_period"]
            save_belief_time = None

        if data.get("train_period") is None and data.get("start_date") is None:
            train_period_in_hours = 30 * 24  # Set default train_period value to 30 days

        elif data.get("train_period") is None and data.get("start_date"):
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

        if data.get("retrain_frequency") is None and data.get("end_date") is not None:
            retrain_frequency_in_hours = int(
                (data["end_date"] - predict_start).total_seconds() / 3600
            )
        elif data.get("retrain_frequency") is None and data.get("end_date") is None:
            retrain_frequency_in_hours = data.get("max_forecast_horizon") // timedelta(
                hours=1
            )
        else:
            retrain_frequency_in_hours = data["retrain_frequency"] // timedelta(hours=1)
            if retrain_frequency_in_hours < 1:
                raise ValidationError("retrain-frequency must be at least 1 hour")

        if data.get("end_date") is None:
            data["end_date"] = predict_start + timedelta(
                hours=retrain_frequency_in_hours
            )

        if data.get("start_date") is None:
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

        model_save_dir = data.get("model_save_dir")
        if model_save_dir is None:
            # Read default from schema
            model_save_dir = self.fields["model_save_dir"].load_default

        ensure_positive = data.get("ensure_positive")

        return dict(
            future_regressors=future_regressors,
            past_regressors=past_regressors,
            target=target_sensor,
            model_save_dir=model_save_dir,
            output_path=output_path,
            start_date=start_date,
            end_date=data["end_date"],
            train_period_in_hours=train_period_in_hours,
            max_training_period=max_training_period,
            predict_start=predict_start,
            predict_period_in_hours=retrain_frequency_in_hours,
            max_forecast_horizon=max_forecast_horizon,
            forecast_frequency=forecast_frequency,
            probabilistic=data["probabilistic"],
            sensor_to_save=sensor_to_save,
            ensure_positive=ensure_positive,
            missing_threshold=data.get("missing_threshold"),
            as_job=data.get("as_job"),
            save_belief_time=save_belief_time,
        )
