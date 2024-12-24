from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.schemas.reporting.profit import (
    ProfitOrLossReporterConfigSchema,
    ProfitOrLossReporterParametersSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.time_utils import server_now
from flexmeasures.data.queries.utils import simplify_index
from flexmeasures.utils.unit_utils import ur, determine_stock_unit, is_currency_unit


class ProfitOrLossReporter(Reporter):
    """Compute the profit or loss due to energy/power flow.

    Given power/energy and price sensors, this reporter computes the profit (revenue - cost)
    or losses (cost - revenue) of a power/energy flow under a certain tariff.

    Sign convention (by default)
    ----------------

    Power flows:
        (+) production
        (-) consumption

    Profit:
        (+) gains
        (-) losses

    This sign convention can be adapted to your needs:
        - The power/energy convention can be inverted by setting the sensor attribute `consumption_is_positive` to True.
        - The output (gains/losses) sign can be inverted by setting the reporter config attribute `loss_is_positive` to False.

    """

    __version__ = "1"
    __author__ = "Seita"

    _config_schema = ProfitOrLossReporterConfigSchema()
    _parameters_schema = ProfitOrLossReporterParametersSchema()

    weights: dict
    method: str

    def _compute_report(
        self,
        start: datetime,
        end: datetime,
        input: list[dict[str, Any]],
        output: list[dict[str, Any]],
        belief_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        :param start: start time of the report
        :param end: end time of the report
        :param input: description of the power/energy sensor, e.g. `input=[{"sensor": 42}]`
        :param output: description of the output sensors where to save the report to.
                       Specify multiple output sensors with different resolutions to save
                       the results in multiple time frames (e.g. hourly, daily),
                       e.g. `output = [{"sensor" : 43}, {"sensor" : 44]}]`
        :param belief_time: datetime used to indicate we are interested in the state of knowledge at that time.
                            It is used to filter input, and to assign a recording time to output.
        """

        production_price_sensor: Sensor = self._config.get("production_price_sensor")
        consumption_price_sensor: Sensor = self._config.get("consumption_price_sensor")
        loss_is_positive: bool = self._config.get("loss_is_positive", False)

        input_sensor: Sensor = input[0]["sensor"]  # power or energy sensor
        input_source: Sensor = input[0].get("sources", None)

        timezone = input_sensor.timezone

        if belief_time is None:
            belief_time = server_now()

        # get prices
        production_price = simplify_index(
            production_price_sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                beliefs_before=belief_time,
                resolution=input_sensor.event_resolution,
                most_recent_beliefs_only=True,
                one_deterministic_belief_per_event=True,
            )
        )
        production_price = production_price.tz_convert(timezone)
        consumption_price = simplify_index(
            consumption_price_sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                beliefs_before=belief_time,
                resolution=input_sensor.event_resolution,
                most_recent_beliefs_only=True,
                one_deterministic_belief_per_event=True,
            )
        )
        consumption_price = consumption_price.tz_convert(timezone)

        # get power/energy time series
        power_energy_data = simplify_index(
            input_sensor.search_beliefs(
                event_starts_after=start,
                event_ends_before=end,
                beliefs_before=belief_time,
                source=input_source,
                most_recent_beliefs_only=True,
                one_deterministic_belief_per_event=True,
            )
        )

        unit_consumption_price = ur.Unit(consumption_price_sensor.unit)
        unit_production_price = ur.Unit(production_price_sensor.unit)

        # compute energy flow from power flow
        if input_sensor.measures_power:
            power_energy_data *= input_sensor.event_resolution / timedelta(hours=1)
            power_energy_unit = ur.Unit(
                determine_stock_unit(input_sensor.unit, time_unit="h")
            )
        else:
            power_energy_unit = ur.Unit(input_sensor.unit)

        # check that the unit of the results are a currency
        cost_unit = unit_consumption_price * power_energy_unit
        revenue_unit = unit_production_price * power_energy_unit
        assert is_currency_unit(cost_unit)
        assert is_currency_unit(revenue_unit)

        # transform time series as to get positive values for production and negative for consumption
        if input_sensor.get_attribute("consumption_is_positive", False):
            power_energy_data *= -1.0

        # compute profit
        # this step assumes that positive flows represent production and negative flows consumption
        result = (
            power_energy_data.clip(lower=0) * production_price
            + power_energy_data.clip(upper=0) * consumption_price
        )

        # transform a losses in negative to positive
        if loss_is_positive:
            result *= -1.0

        results = []

        output_name = "profit"

        if loss_is_positive:
            output_name = "loss"

        for output_description in output:
            output_sensor = output_description["sensor"]
            _result = result.copy()

            # resample result to the event_resolution of the output sensor
            _result = _result.resample(output_sensor.event_resolution).sum()

            # convert BeliefsSeries into a BeliefsDataFrame
            _result["belief_time"] = belief_time
            _result["cumulative_probability"] = 0.5
            _result["source"] = self.data_source
            _result.sensor = output_sensor
            _result.event_resolution = output_sensor.event_resolution

            # check output sensor unit coincides with the units of the result
            assert str(cost_unit) == output_sensor.unit
            assert str(revenue_unit) == output_sensor.unit

            _result = _result.set_index(
                ["belief_time", "source", "cumulative_probability"], append=True
            )

            results.append(
                {
                    "name": output_name,
                    "column": "event_value",
                    "sensor": output_description["sensor"],
                    "data": _result,
                }
            )

        return results
