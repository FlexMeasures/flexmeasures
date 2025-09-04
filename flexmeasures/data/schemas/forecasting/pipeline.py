from __future__ import annotations

import os
import click
import json

from datetime import timedelta

from marshmallow import fields, Schema, validates_schema, post_load, ValidationError

from flexmeasures.data import db
from flexmeasures.data.schemas import SensorIdField
from flexmeasures.data.schemas.times import AwareDateTimeOrDateField, DurationField
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.forecasting.utils import floor_to_resolution
from flexmeasures.utils.time_utils import server_now


class ForecastingPipelineSchema(Schema):

    sensor = SensorIdField(required=True)
    regressors = fields.Str(
        required=False, allow_none=True
    )  # expects comma-separated Sensor id's like "2092,2093"
    past_regressors = fields.Str(
        required=False, allow_none=True
    )  # expects comma-separated Sensor id's
    future_regressors = fields.Str(
        required=False, allow_none=True
    )  # expects comma-separated Sensor id's
    model_save_dir = fields.Str(required=True)
    output_path = fields.Str(required=False, allow_none=True)
    start_date = AwareDateTimeOrDateField(required=False, allow_none=True)
    end_date = AwareDateTimeOrDateField(required=True, inclusive=True)
    train_period = fields.Int(required=False, allow_none=True)
    start_predict_date = AwareDateTimeOrDateField(required=False, allow_none=True)
    predict_period = fields.Int(required=False, allow_none=True)
    max_forecast_horizon = DurationField(
        required=False, allow_none=True, load_default=timedelta(hours=48)
    )
    forecast_frequency = DurationField(
        required=False, allow_none=True, load_default=timedelta(hours=1)
    )
    probabilistic = fields.Bool(required=True)
    sensor_to_save = SensorIdField(required=False, allow_none=True)

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):
        start_date = data["start_date"]
        end_date = data["end_date"]
        predict_start = data.get("start_predict_date", None)
        train_period = data.get("train_period")
        predict_period = data.get("predict_period")
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

        if train_period is not None and train_period < 2:
            raise ValidationError(
                "train-period must be at least 2 days (48 hours)",
                field_name="train_period",
            )

        if predict_period is not None and predict_period <= 0:
            raise ValidationError(
                "predict-period must be greater than 0", field_name="predict_period"
            )

        if max_forecast_horizon is not None:
            if max_forecast_horizon % sensor.event_resolution != timedelta(0):
                raise ValidationError(
                    f"max-forecast-horizon must be a multiple of the sensor resolution ({sensor.event_resolution})"
                )
            else:
                data["max_forecast_horizon"] = (
                    data["max_forecast_horizon"] // sensor.event_resolution
                )

        if forecast_frequency is not None:
            if forecast_frequency % sensor.event_resolution != timedelta(0):
                raise ValidationError(
                    f"forecast-frequency must be a multiple of the sensor resolution ({sensor.event_resolution})"
                )
            else:
                data["forecast_frequency"] = (
                    data["forecast_frequency"] // sensor.event_resolution
                )

    def _parse_comma_list(self, text: str | None) -> list[str]:
        if not text:
            return []
        sensors_names = []
        for idx, sensor_id in enumerate(text.split(","), start=1):
            sensor_id = sensor_id.strip()
            if sensor_id:
                sensor = db.session.get(Sensor, int(sensor_id))
                if sensor is None:
                    raise ValidationError(f"Sensor id {sensor_id} not found in DB.")
                sensors_names.append(f"{sensor.name} (ID: {sensor_id})")
        return sensors_names

    def _parse_json_dict(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValidationError(
                "sensors must be a valid JSON string mapping names to IDs",
                field_name="sensors",
            )

    def _build_sensors_dict(
        self,
        target_sensor: Sensor,
        regressors: str,
        future_regressors: str,
        past_regressors: str,
    ) -> dict:

        sensors_dict = {
            f"{target_sensor.name} (ID: {target_sensor.id})": target_sensor.id
        }

        # Split both regressors and future_regressors and merge them
        all_ids = set()
        if regressors:
            all_ids.update(int(x.strip()) for x in regressors.split(",") if x.strip())
        if future_regressors:
            all_ids.update(
                int(x.strip()) for x in future_regressors.split(",") if x.strip()
            )
        if past_regressors:
            all_ids.update(
                int(x.strip()) for x in past_regressors.split(",") if x.strip()
            )

        # Add them to the dict with unique keys
        for idx, sensor_id in enumerate(sorted(all_ids), start=1):
            sensors_dict[
                f"{db.session.get(Sensor, sensor_id).name} (ID: {sensor_id})"
            ] = sensor_id

        return sensors_dict

    @post_load
    def resolve_config(self, data: dict, **kwargs) -> dict:  # noqa: C901

        regressors = self._parse_comma_list(data.get("regressors", ""))
        future_regressors = self._parse_comma_list(data.get("future_regressors", ""))
        past_regressors = self._parse_comma_list(data.get("past_regressors", ""))
        sensors = self._build_sensors_dict(
            target_sensor=data["sensor"],
            regressors=data.get("regressors", ""),
            future_regressors=data.get("future_regressors", ""),
            past_regressors=data.get("past_regressors", ""),
        )
        target_sensor = data["sensor"]

        if regressors:
            future_regressors.extend(regressors)
            future_regressors = list(set(future_regressors))
            past_regressors.extend(regressors)
            past_regressors = list(set(past_regressors))

        future = [
            db.session.get(Sensor, int(x.strip()))
            for x in data.get("future_regressors", "").split(",")
            if x.strip()
        ]
        past = [
            db.session.get(Sensor, int(x.strip()))
            for x in data.get("past_regressors", "").split(",")
            if x.strip()
        ]

        resolution = target_sensor.event_resolution

        predict_start = data.get("start_predict_date") or floor_to_resolution(
            server_now(), resolution
        )
        if data.get("start_predict_date") is None and data.get("train_period"):

            predict_start = data["start_date"] + timedelta(
                hours=data["train_period"] * 24
            )

        if data.get("train_period") is None and data["start_date"] is None:
            train_period_in_hours = 30 * 24  # Set default train_period value to 30 days

        elif data.get("train_period") is None and data["start_date"]:
            train_period_in_hours = int(
                (predict_start - data["start_date"]).total_seconds() / 3600
            )
        else:
            train_period_in_hours = data["train_period"] * 24

        if train_period_in_hours < 48:
            raise click.BadParameter(
                "--train-period must be at least 2 days (48 hours)."
            )

        if data.get("predict_period") is None:
            predict_period_in_hours = int(
                (data["end_date"] - predict_start).total_seconds() / 3600
            )
        else:
            predict_period_in_hours = data["predict_period"] * 24
            if predict_period_in_hours < 1:
                raise click.BadParameter("--predict-period must be at least 1 hour")

        if data["start_date"] is None:
            start_date = predict_start - timedelta(hours=train_period_in_hours)
        else:
            start_date = data["start_date"]

        max_forecast_horizon = data.get("max_forecast_horizon")
        forecast_frequency = data.get("forecast_frequency")

        if max_forecast_horizon is None and forecast_frequency is None:
            multiplier = timedelta(hours=1) // data["sensor"].event_resolution
            max_forecast_horizon = predict_period_in_hours * multiplier
            forecast_frequency = predict_period_in_hours * multiplier
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

        return dict(
            sensors=sensors,
            past_regressors=past_regressors,
            future_regressors=future_regressors,
            future=future,
            past=past,
            target=target_sensor,
            model_save_dir=data["model_save_dir"],
            output_path=output_path,
            start_date=start_date,
            end_date=data["end_date"],
            train_period_in_hours=train_period_in_hours,
            predict_start=predict_start,
            predict_period_in_hours=predict_period_in_hours,
            max_forecast_horizon=max_forecast_horizon,
            forecast_frequency=forecast_frequency,
            probabilistic=data["probabilistic"],
            sensor_to_save=sensor_to_save,
        )
