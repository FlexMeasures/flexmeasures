import pytest

from datetime import timedelta
from flexmeasures.data.models.reporting.profit import ProfitOrLossReporter
from flexmeasures.data.models.time_series import Sensor
from datetime import datetime
from pytz import timezone


@pytest.mark.parametrize(
    "use_power_sensor, loss_is_positive",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_profit_reporter(app, db, profit_report, use_power_sensor, loss_is_positive):
    (
        profit_sensor_hourly,
        profit_sensor_daily,
        power_sensor,
        energy_sensor,
    ) = profit_report
    output_sensor = energy_sensor

    if use_power_sensor:
        output_sensor = power_sensor

    epex_da = Sensor.query.filter(Sensor.name == "epex_da").one_or_none()
    epex_da_production = Sensor.query.filter(
        Sensor.name == "epex_da_production"
    ).one_or_none()

    profit_reporter = ProfitOrLossReporter(
        consumption_price_sensor=epex_da,
        production_price_sensor=epex_da_production,
        loss_is_positive=loss_is_positive,
    )

    sign = 1.0

    if loss_is_positive:
        sign = -1.0

    tz = timezone("Europe/Amsterdam")

    result = profit_reporter.compute(
        start=tz.localize(datetime(2015, 1, 3)),
        end=tz.localize(datetime(2015, 1, 4)),
        input=[dict(sensor=output_sensor)],
        output=[
            dict(sensor=profit_sensor_hourly),
            dict(sensor=profit_sensor_daily),
        ],
    )

    result_hourly = result[0]["data"]
    result_daily = result[1]["data"]

    assert result_hourly.event_resolution == timedelta(hours=1)

    # period of negative prices

    # in the period from 00:00 to 03:00
    # the device produces 100kWh hourly at a -50 EUR/MWh price
    assert (result_hourly[0:4] == -5 * sign).event_value.all()

    # in the period from 04:00 to 08:00
    # the device consumes 100kWh hourly at a 10 EUR/MWh price
    assert (result_hourly[4:8] == 1 * sign).event_value.all()

    # period of positive prices

    # in the period from 08:00 to 12:00
    # the device produces 100kWh hourly at a 60 EUR/MWh price
    assert (result_hourly[8:12] == 6 * sign).event_value.all()

    # in the period from 12:00 to 16:00
    # the device produces 100kWh hourly at a 100 EUR/MWh price
    assert (result_hourly[12:16] == -10 * sign).event_value.all()

    assert result_daily.event_value.iloc[0] == result_hourly.sum().iloc[0]
