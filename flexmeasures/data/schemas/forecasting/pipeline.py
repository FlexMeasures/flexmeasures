from marshmallow import fields, Schema, validates_schema

from flexmeasures.data.schemas import AwareDateTimeField, SensorIdField


class ForecastingPipelineSchema(Schema):

    sensors = fields.Str(required=True)  # expects JSON string like '{"target": 123, "Ta": 456}'
    regressors = fields.Str(required=False, allow_none=True)  # expects comma-separated string like "target,Ta"
    future_regressors = fields.Str(required=False, allow_none=True)  # expects comma-separated string
    target = fields.Str(required=True)
    model_save_dir = fields.Str(required=True)
    output_path = fields.Str(required=False, allow_none=True)
    start_date = AwareDateTimeField(required=True)
    end_date = AwareDateTimeField(required=True)
    train_period = fields.Int(required=False, allow_none=True)
    start_predict_date = AwareDateTimeField(required=False, allow_none=True)
    predict_period = fields.Int(required=False, allow_none=True)
    max_forecast_horizon = fields.Int(required=False, allow_none=True)
    forecast_frequency = fields.Int(required=False, allow_none=True)
    probabilistic = fields.Bool(required=True)
    sensor_to_save = SensorIdField(required=False, allow_none=True)

    @validates_schema
    def validate_parameters(self, data: dict, **kwargs):
        start_date = data["start_date"]
        end_date = data["end_date"]
        predict_start = data.get("start_predict_date", None)
        train_period = data.get("train_period")
        predict_period = data.get("predict_period")

        if start_date >= end_date:
            raise ValidationError("--start-date must be before --end-date", field_name="start_date")

        if predict_start:
            if predict_start < start_date:
                raise ValidationError("--start-predict-date cannot be before --start-date", field_name="start_predict_date")
            if predict_start >= end_date:
                raise ValidationError("--start-predict-date must be before --end-date", field_name="start_predict_date")

        if train_period is not None and train_period < 2:
            raise ValidationError("--train-period must be at least 2 days (48 hours)", field_name="train_period")

        if predict_period is not None and predict_period <= 0:
            raise ValidationError("--predict-period must be greater than 0", field_name="predict_period")

        regressors = self._parse_comma_list(data.get("regressors", ""))
        future_regressors = self._parse_comma_list(data.get("future_regressors", ""))
        if not regressors and not future_regressors:
            raise ValidationError("At least one of --regressors or --future-regressors must be provided", field_name="regressors")

    def _parse_comma_list(self, text: str | None) -> list[str]:
        return [item.strip() for item in text.split(",") if item.strip()] if text else []

