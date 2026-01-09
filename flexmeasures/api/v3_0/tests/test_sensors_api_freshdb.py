import io
import pytest
from datetime import timedelta

from flask import url_for
from sqlalchemy import select
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.api.v3_0.tests.utils import generate_csv_content


@pytest.mark.parametrize(
    "requesting_user, sensor_index, data_unit, data_resolution, data_values, expected_event_values, expected_status",
    [
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "m/s",  # Invalid conversion                        - m/s to kW
            timedelta(hours=1),  # Upsampling                   - 1 hour to 15 minutes
            [45.3, 45.3],
            "Provided unit 'm/s' is not convertible to sensor unit 'kW'",
            422,  # units not convertible
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kWh",  # No conversion needed                      - kWh to kWh
            timedelta(hours=1),  # No resampling                - 1 hour to 1 hour
            [45.3] * 4,
            [45.3] * 4,  # same unit and resolution - values stay the same
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            0,  # this sensor has unit=MW, res=00:15
            "kWh",  # Conversion needed                         - kWh to MW
            timedelta(hours=1),  # Upsampling                   - 1 hour to 15 minutes
            [45.3] * 4,
            [45.3 / 1000.0]
            * 4
            * 4,  # values: / 1000 due to kW(h)->MW, number *4 due to h->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "MW",  # Conversion needed                          - MW to kW
            timedelta(hours=1),  # Upsampling                   - 1 hour to 15 minutes
            [2] * 6,
            [2 * 1000]
            * 6
            * 4,  # both power units, so 2 MW = 2000 kW, number *4 due to h->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "kWh",  # Conversion needed                         - kWh to kW
            # Upsampling                                        - 30 minutes to 15 minutes
            timedelta(minutes=30),
            [10] * 12,
            [10 * 2]
            * 12
            * 2,  # 10 kWh per half hour = 20 kW power, number *2 due to 30min->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kWh",  # No conversion needed                      - kWh to kWh
            timedelta(minutes=30),  # Downsampling              - 30 minutes to 1 hour
            [10, 20, 20, 40],
            [
                30,
                60,
            ],  # we make (10 + 20) kWh the first hour, and (20 + 40) kWh the second hour
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kW",  # Conversion needed                          - kW to kWh
            timedelta(minutes=30),  # Downsampling              - 30 minutes to 1 hour
            [20, 40, 40, 80],
            "Provided unit 'kW' is not convertible to sensor unit 'kWh'",
            422,  # we don't support this case yet
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "kWh",  # Conversion needed                         - kWh to kW
            # Downsampling                                      - 7.5 minutes to 15 minutes
            timedelta(minutes=7, seconds=30),
            [20, 40, 40, 80],
            [
                240,
                480,
            ],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "MW",  # Conversion needed                          - MW to kW
            # Downsampling                                      - 7.5 minutes to 15 minutes
            timedelta(minutes=7, seconds=30),
            [20, 40, 40, 80, 30, 60],
            [
                30000,
                60000,
                45000,
            ],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            3,  # this sensor has unit=kWh, res=00:00
            "MWh",  # Conversion needed                         - MWh to kWh
            # No resampling                                     - 7.5 minutes to instantaneous
            timedelta(minutes=7, seconds=30),
            [10, 20, 40, 80],
            [10000, 20000, 40000, 80000],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            3,  # this sensor has unit=kWh, res=00:00
            "kW",  # Conversion needed                          - kW to kWh
            # No resampling                                     - 7.5 minutes to instantaneous
            timedelta(minutes=7, seconds=30),
            [20, 40, 40, 80],
            "Provided unit 'kW' is not convertible to sensor unit 'kWh'",
            422,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            4,  # this sensor has unit=EUR/kWh, res=01:00
            "EUR/MWh",  # Conversion needed                     - EUR/MWh to EUR/kWh
            timedelta(minutes=30),  # Downsampling              - 30 minutes to 1 hour
            [200, 300, 400, 500],
            [0.25, 0.45],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            4,  # this sensor has unit=EUR/kWh, res=01:00
            "EUR/kWh",  # Conversion needed                     - EUR/kWh to EUR/kWh
            timedelta(hours=2),  # Upsampling                   - 2 hours to 1 hour
            [200, 300, 400],
            [200, 200, 300, 300, 400, 400],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            5,  # this sensor has unit=EUR, res=01:00
            "kEUR",  # Conversion needed                        - kEUR to EUR
            timedelta(minutes=30),  # Downsampling              - 30 minutes to 1 hour
            [2, 3, 4, 2],
            # we make (2 + 3) kEUR the first hour, and (4 + 2) kEUR the second hour
            [5000, 6000],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            5,  # this sensor has unit=EUR, res=01:00
            "kEUR",  # Conversion needed                        - kEUR to EUR
            timedelta(hours=2),  # Upsampling                   - 2 hours to 1 hour
            [5, 6],
            # we make:
            # - (2.5 + 2.5) kEUR the first two hours
            # - (3   + 3  ) kEUR the second two hours
            # - (3.5 + 3.5) kEUR the third two hours
            [2500, 2500, 3000, 3000],
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            5,  # this sensor has unit=EUR, res=01:00
            "kEUR",  # Conversion needed                        - kEUR to EUR
            timedelta(hours=1),  # No resampling                - 1 hour (!) to 1 hour
            # Note that this test case could also define 2 hours between rows, but since there is only 1 row of data,
            # the data does not actually contain any 2-hour delta.
            # Therefore, FlexMeasures assumes the data resolution already matches the sensor resolution.
            [5],
            [5000],  # we make 5 kEUR the first hour
            200,
        ),
    ],
    indirect=["requesting_user"],
)
def test_auth_upload_sensor_data_with_distinct_to_from_units_and_target_resolutions(
    fresh_db,
    client,
    add_battery_assets_fresh_db,
    requesting_user,
    sensor_index,
    data_unit,
    data_resolution,
    data_values,
    expected_event_values,
    expected_status,
):
    """
    Check if unit validation works fine for sensor data upload.
    The target sensors can have different units and resolution,
    and the incoming data can also have differing resolutions and declared unit.
    This test needs to check if the resulting data matches expectations.
    """

    start_date = (
        "2025-01-01T10:00:00+00:00"  # This date would be used to generate CSV content
    )
    test_battery = add_battery_assets_fresh_db["Test battery"]
    sensor = test_battery.sensors[sensor_index]
    num_test_intervals = len(data_values)
    print(
        f"Uploading data to sensor '{sensor.name}' with unit={sensor.unit} and resolution={sensor.event_resolution}."
    )
    print(f"Data unit is {data_unit} and resolution is {data_resolution}")

    csv_content = generate_csv_content(
        start_time_str=start_date,
        interval=data_resolution,
        values=data_values,
    )
    print("Generated CSV content:")
    print(csv_content)
    file_obj = io.BytesIO(csv_content.encode("utf-8"))

    response = client.post(
        url_for("SensorAPI:upload_data", id=sensor.id),
        data={"uploaded-files": (file_obj, "data.csv"), "unit": data_unit},
        content_type="multipart/form-data",
    )
    print("Response:\n%s" % response.status_code, expected_status)
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == expected_status

    # fetch the save timedBeliefs and check if they have the right values
    if response.status_code == 200:
        timed_beliefs = fresh_db.session.execute(
            select(TimedBelief)
            .filter(TimedBelief.sensor_id == sensor.id)
            .order_by(TimedBelief.event_start)
        ).scalars()

        beliefs = timed_beliefs.all()
        bdf = BeliefsDataFrame(beliefs)
        print("Stored beliefs: ==============================")
        print(bdf)

        expected_num_beliefs = num_test_intervals
        if sensor.event_resolution != timedelta(0):
            expected_num_beliefs *= data_resolution / sensor.event_resolution
        assert (
            len(beliefs) == expected_num_beliefs
        ), f"Fetched {len(beliefs)} beliefs from the database, expecting {expected_num_beliefs}."

        assert [b.event_value for b in beliefs] == expected_event_values
    elif response.status_code == 422:
        assert (
            expected_event_values
            in response.json["message"]["combined_sensor_data_upload"]["_schema"]
        )
