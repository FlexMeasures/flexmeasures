"""A deterministic ingestion plugin for exercising automation execution."""

from flask import Blueprint
from marshmallow import Schema, fields
import timely_beliefs as tb

from flexmeasures.data.automations import AutomationHandler
from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.schemas.sensors import SensorIdField

__version__ = "1.0"
blueprint = Blueprint("mock_automation_ingestion", __name__)


class IngestionConfigSchema(Schema):
    sensor = SensorIdField(required=True)
    input_sensor = SensorIdField(required=False, data_key="input-sensor")


class IngestionParametersSchema(Schema):
    value = fields.Float(load_default=42.0)


class MockIngestionGenerator(DataGenerator):
    __data_generator_base__ = "ingestor"
    __version__ = "1.0"
    _config_schema = IngestionConfigSchema()
    _parameters_schema = IngestionParametersSchema()

    @property
    def input_sensors(self):
        return self._resolve_sensors(self._config.get("input_sensor"))

    @property
    def output_sensors(self):
        return [self._config["sensor"]]

    def _compute(self, value):
        sensor = self._config["sensor"]
        beliefs = tb.BeliefsDataFrame(
            [
                tb.TimedBelief(
                    sensor=sensor,
                    source=self.data_source,
                    event_start="2026-01-01T00:00:00+00:00",
                    belief_horizon="PT0H",
                    event_value=value,
                )
            ]
        )
        return [{"sensor": sensor, "data": beliefs}]


__automation_types__ = [
    AutomationHandler(
        type_id="mock-ingestion",
        display_name="Mock ingestion",
        generator_class=MockIngestionGenerator,
        queue="ingestion",
        result_noun="measurement",
    )
]
