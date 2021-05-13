from marshmallow import validates, ValidationError, fields, validate

from flexmeasures.data import ma
from flexmeasures.data.models.weather import WeatherSensor, WeatherSensorType
from flexmeasures.data.schemas.sensors import SensorSchemaMixin


class WeatherSensorSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    WeatherSensor schema, with validations.
    """

    class Meta:
        model = WeatherSensor

    @validates("name")
    def validate_name(self, name: str):
        sensor = WeatherSensor.query.filter(
            WeatherSensor.name == name.lower()
        ).one_or_none()
        if sensor:
            raise ValidationError(
                f"A weather sensor with the name {name} already exists."
            )

    @validates("weather_sensor_type_name")
    def validate_weather_sensor_type(self, weather_sensor_type_name: str):
        weather_sensor_type = WeatherSensorType.query.get(weather_sensor_type_name)
        if not weather_sensor_type:
            raise ValidationError(
                f"Weather sensor type {weather_sensor_type_name} doesn't exist."
            )

    weather_sensor_type_name = ma.auto_field(required=True)
    latitude = fields.Float(required=True, validate=validate.Range(min=-90, max=90))
    longitude = fields.Float(required=True, validate=validate.Range(min=-180, max=180))
