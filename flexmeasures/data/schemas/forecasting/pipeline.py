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

    @validates_schema()
    def validate_timing_parameters(self, data: dict, **kwargs) -> dict:
        # todo: move resolve_forecast_config here
        return data
