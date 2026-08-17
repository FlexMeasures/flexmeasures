from marshmallow import Schema, ValidationError
import pytest

from flexmeasures.data.services.reporting import create_reporting_job


class EmptyParametersSchema(Schema):
    pass


class ReporterWithoutDataflow:
    _parameters_schema = EmptyParametersSchema()
    _parameters = {}

    @property
    def data_source(self):
        raise AssertionError(
            "The data source was accessed before parameter validation."
        )


def test_create_reporting_job_validates_dataflow_before_accessing_source():
    reporter = ReporterWithoutDataflow()

    with pytest.raises(ValidationError) as exc_info:
        create_reporting_job(reporter)  # type: ignore[arg-type]

    assert set(exc_info.value.messages) == {"input", "output"}
