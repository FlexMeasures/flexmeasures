from __future__ import annotations

from typing import Any

import timely_beliefs as tb

from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.models.time_series import Sensor

from flexmeasures.data.schemas.reporting import (
    ReporterParametersSchema,
    ReporterConfigSchema,
)
from flexmeasures.utils.bound_utils import apply_bounds_to_values, parse_bounds

#: The keys an input entry carries to clean the readings it asks for, rather than to search with.
INPUT_BOUND_KEYS = ("lower", "upper", "snap")


def read_input_beliefs(
    sensor: Sensor, search_parameters: dict, **search_criteria
) -> tb.BeliefsDataFrame:
    """Read a report input's beliefs, cleaned against the bounds that input carries.

    An input entry may say how to clean the readings it asks for, the way a forecaster's regressors and a scheduler's references can.
    Those keys are taken out of the search, which would not know what to do with them, and applied to what the search returns.
    The bounds are read in the sensor's own unit, and snapping runs before clipping, as everywhere else.

    :param sensor:            The sensor the input names.
    :param search_parameters: What is left of the input entry, which this function takes the bounds out of.
    :param search_criteria:   The search criteria the reporter decided on, such as the event window.
    :returns:                 The beliefs, with their values snapped and clipped where the input asked for it.
    """
    bounds = {key: search_parameters.pop(key, None) for key in INPUT_BOUND_KEYS}
    beliefs = sensor.search_beliefs(**search_criteria, **search_parameters)
    if bounds["lower"] is None and bounds["upper"] is None and not bounds["snap"]:
        return beliefs

    lower_value, upper_value, snap_intervals = parse_bounds(
        bounds["lower"],
        bounds["upper"],
        bounds["snap"],
        sensor.unit,
        label=f"bounds on sensor {sensor.name} (ID: {sensor.id})",
    )
    beliefs["event_value"] = apply_bounds_to_values(
        beliefs["event_value"].to_numpy(), lower_value, upper_value, snap_intervals
    )
    return beliefs


class Reporter(DataGenerator):
    """Superclass for all FlexMeasures Reporters."""

    __version__ = None
    __author__ = None
    __data_generator_base__ = "reporter"

    _parameters_schema = ReporterParametersSchema()
    _config_schema = ReporterConfigSchema()

    @property
    def input_sensors(self) -> list:
        """Return the sensors from which the report reads input data."""
        parameters = self._parameters or {}
        return self._resolve_sensors(
            [item.get("sensor") for item in parameters.get("input", [])]
        )

    @property
    def output_sensors(self) -> list:
        """Return the sensors on which the report records its results."""
        parameters = self._parameters or {}
        return self._resolve_sensors(
            [item.get("sensor") for item in parameters.get("output", [])]
        )

    def _compute(
        self, check_output_resolution=True, as_job: bool = False, **kwargs
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """This method triggers the creation of a new report.

        The same object can generate multiple reports with different start, end, resolution and belief_time values.

        :param check_output_resolution: If True, checks each output for whether the event_resolution
                                        matches that of the sensor it is supposed to be recorded on.
        :param as_job:                  If True, queue a reporting job instead of computing immediately.
        :returns:                       A dictionary with ``job_id`` and ``n_jobs`` when queued,
                                        otherwise the computed report results.
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
