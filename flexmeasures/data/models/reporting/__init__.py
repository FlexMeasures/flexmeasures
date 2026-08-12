from __future__ import annotations

from typing import Any
from flexmeasures.data.models.data_sources import DataGenerator

from flexmeasures.data.schemas.reporting import (
    ReporterParametersSchema,
    ReporterConfigSchema,
)


class Reporter(DataGenerator):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "reporter"

    _parameters_schema = ReporterParametersSchema()
    _config_schema = ReporterConfigSchema()

    @property
    def input_sensors(self) -> list:
        """The sensors from which the report reads its input data."""
        parameters = self._parameters or {}
        return self._resolve_sensors(
            [
                input_description.get("sensor")
                for input_description in parameters.get("input", [])
            ]
        )

    @property
    def output_sensors(self) -> list:
        """The sensors on which the report records its results."""
        parameters = self._parameters or {}
        return self._resolve_sensors(
            [
                output_description.get("sensor")
                for output_description in parameters.get("output", [])
            ]
        )

    def _compute(
        self, check_output_resolution=True, as_job: bool = False, **kwargs
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution and belief_time values.

        :param check_output_resolution: If True, checks each output for whether the event_resolution
                                        matches that of the sensor it is supposed to be recorded on.
        :param as_job:                  If True, a job to compute (and save) the report is queued instead,
                                        and a dict like {"job_id": <uuid>, "n_jobs": 1} is returned.
        """
        if as_job:
            from flexmeasures.data.services.reporting import create_reporting_job

            job = create_reporting_job(self)
            return {"job_id": job.id, "n_jobs": 1}

        results = self._compute_report(**kwargs)

        for result in results:
            # checking that the event_resolution of the output BeliefDataFrame is equal to the one of the output sensor
            assert not check_output_resolution or (
                result["sensor"].event_resolution == result["data"].event_resolution
            ), f"The resolution of the results ({result['data'].event_resolution}) should match that of the output sensor ({result['sensor'].event_resolution}, ID {result['sensor'].id})."

        return results

    def _compute_report(self, **kwargs) -> list[dict[str, Any]]:
        """Overwrite with the actual computation of your report.

        :returns list of dictionaries, for example:
                 [
                     {
                         "sensor": 501,
                         "data": <a BeliefsDataFrame>,
                     },
                 ]
        """
        raise NotImplementedError()
