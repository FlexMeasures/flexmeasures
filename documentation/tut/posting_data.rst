.. _tut_posting_data:

Ingesting data from files and scripts
======================================

FlexMeasures turns time-series data into forecasts, reports and optimized schedules.
This tutorial shows how to build the first part of that journey: an automated data-ingestion pipeline.
In this tutorial, we build a complete script which you can run from the command line.

You will upload a CSV or Excel file with the `FlexMeasures Client <https://github.com/FlexMeasures/flexmeasures-client/>`_,
verify the stored values, and then adapt the example to values produced by an export script.
The same API accepts meter readings, prices, weather data, state of charge and other numeric time series.

.. contents:: Table of contents
    :local:
    :depth: 2

Choosing an ingestion route
---------------------------

Most production pipelines should use the FlexMeasures Client or the API.
The UI upload is useful for a quick first success and for checking whether a file is accepted before automating it.

=============================== ================================================
Situation                       Recommended route
=============================== ================================================
Values available in Python      FlexMeasures Client
CSV or Excel on another system  FlexMeasures Client or file-upload API
Another programming language    REST API
Quickly validate a file         Sensor UI
One-off import on the server    FlexMeasures CLI
Reusable third-party connector  FlexMeasures plugin
=============================== ================================================

Prerequisites
-------------

You need:

- a running FlexMeasures server;
- the hostname and login details of a user allowed to record data;
- the ID of an existing sensor;
- the sensor's unit, event resolution and timezone; and
- Python 3.10 or newer.

A sensor is the contract for a time series: it tells FlexMeasures what the values mean,
which unit they use, how long each event lasts and which timezone applies.
Ask the administrator of your FlexMeasures organisation for these details,
or find the sensor in the UI.
If you host FlexMeasures yourself, :ref:`getting_started` and :ref:`cli` explain how to create the required structure.

For a recurring pipeline, consider a dedicated integration user.
FlexMeasures records the authenticated user as the data source, making the pipeline's provenance easy to recognize.

Install version 0.9.4 or newer of the client:

.. code-block:: console

    $ pip install "flexmeasures-client>=0.9.4"

Store connection details outside the script, for example as environment variables:

.. code-block:: console

    $ export FLEXMEASURES_HOST="company.flexmeasures.io"
    $ export FLEXMEASURES_EMAIL="data-pipeline@example.com"
    $ export FLEXMEASURES_SENSOR_ID="16"

When you run the complete script, it securely prompts for the password without recording it in your shell history.
For an unattended pipeline, inject ``FLEXMEASURES_PASSWORD`` from your deployment platform's secret manager.

Preparing a file
----------------

The simplest input has two columns: an event start and a numeric value.
For example, a 15-minute power time series may look like this:

.. code-block:: text

    event_start,event_value
    2026-07-30T08:00:00+02:00,4.2
    2026-07-30T08:15:00+02:00,4.8
    2026-07-30T08:30:00+02:00,5.1
    2026-07-30T08:45:00+02:00,4.6

Save this as ``meter-readings.csv``, or put the same two columns in ``meter-readings.xlsx``.
CSV, XLSX, XLS and XLSM files are supported.

Use timezone-aware ISO 8601 timestamps when possible.
If timestamps have no UTC offset, FlexMeasures interprets them in the sensor's timezone.
Explicit offsets avoid ambiguity around daylight-saving-time transitions.
Aligning timestamps and frequency with the sensor's event resolution also makes the pipeline easier to reason about,
although FlexMeasures can resample compatible resolutions.

Optionally validate the file in the UI
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Before automating the pipeline, you can test the file on the sensor page:

1. Open the relevant sensor.
2. Expand **Upload data** in the left side panel.
3. Choose the file and its unit.
4. Select **Measured instantly** if each value was known when its event ended.
5. Upload the file and inspect the chart.

The panel also offers an example Excel file.
If the UI accepts your file but the automated upload does not,
focus troubleshooting on the client configuration, credentials and network connection rather than the file format.

.. A future screenshot belongs here. It should show the sensor page with the
   "Upload data" panel expanded, including the file selector, "Measured
   instantly" checkbox, unit selector and upload button.

Uploading the file with the FlexMeasures Client
-----------------------------------------------

The following call works for both CSV and Excel files:

.. literalinclude:: scripts/run-data-ingestion.py
    :language: python
    :start-after: # Start file upload example
    :end-before: # End file upload example
    :dedent: 12

``belief_time_measured_instantly=True`` records each value as known when its event ended.
Leave it at the default ``False`` when the values only became known at upload time.

The file upload currently assumes that values use the sensor's unit.
The UI and raw API additionally let you specify a different compatible input unit for conversion.

On a server with an ingestion worker, the request may return ``202 Accepted`` while the file is processed in the background.
Client 0.9.4 accepts both synchronous and queued responses.
Do not assume that accepted data is immediately available; verify it or follow the returned job URL before starting dependent work.

.. _posting_sensor_data:

Posting values from an export script
------------------------------------

Often a script has already fetched or computed the values, so writing an intermediate file is unnecessary.
Post an equally spaced sequence directly:

.. literalinclude:: scripts/run-data-ingestion.py
    :language: python
    :start-after: # Start export script example
    :end-before: # End export script example
    :dedent: 8

The number of values and the duration determine their frequency.
For example, four values over ``PT1H`` represent four 15-minute events.
The duration covers the complete events, so it is one hour rather than the 45-minute difference between the first and last timestamps.

For data collected dynamically, the surrounding pipeline could look like this:

.. code-block:: python

    import asyncio
    import getpass
    import os

    from flexmeasures_client import FlexMeasuresClient


    async def main():
        email = os.environ["FLEXMEASURES_EMAIL"]
        client = FlexMeasuresClient(
            host=os.environ["FLEXMEASURES_HOST"],
            ssl=True,
            email=email,
            password=os.getenv("FLEXMEASURES_PASSWORD")
            or getpass.getpass(f"FlexMeasures password for {email}: "),
        )
        try:
            values = export_latest_meter_values()  # Your database or vendor API
            await client.post_sensor_data(
                sensor_id=int(os.environ["FLEXMEASURES_SENSOR_ID"]),
                start="2026-07-30T08:00:00+02:00",
                duration="PT1H",
                values=values,
                unit="kW",
            )
        finally:
            await client.close()


    asyncio.run(main())

The client expects a hostname without ``https://``; set ``ssl=True`` for HTTPS.
The vendor-specific placeholder ``export_latest_meter_values()`` must return a ``list[float]``, ordered from the oldest interval to the newest.

Verifying the result
--------------------

Reading values back is not required for ingestion.
We do it here for the sake of the tutorial, to demonstrate that the pipeline stored the expected data.
Read back the same interval:

.. code-block:: python

    sensor_data = await client.get_sensor_data(
        sensor_id=sensor_id,
        start="2026-07-30T08:00:00+02:00",
        duration="PT1H",
        resolution="PT15M",
        unit="kW",
    )
    assert sensor_data["values"] == [4.2, 4.8, 5.1, 4.6]

You can also inspect the sensor chart in the UI.
Verifying the values, unit and interval catches mistakes that a successful HTTP response alone cannot.

Running the executable tutorial
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The complete script uploads an example Excel file,
posts a second interval as in-memory values and verifies both results:

.. code-block:: console

    $ uv run --no-project --with "flexmeasures-client>=0.9.4" \
        python documentation/tut/scripts/run-data-ingestion.py \
        --sensor-id 16 --unit EUR/MWh --resolution PT1H

FlexMeasures maintainers can run the corresponding Docker QA wrapper against the development stack:

.. code-block:: console

    $ ./documentation/tut/scripts/run-data-ingestion-in-docker.sh

The same runner is used in CI so that the client examples in this tutorial remain executable.

Making the pipeline reliable
----------------------------

For a recurring pipeline:

- store the last successfully ingested timestamp or derive the next window from the source system;
- retry transient connection failures with bounded backoff;
- log the sensor ID, interval, number of values and ingestion job ID;
- split large histories into bounded requests (the server limit defaults to 3 MiB per request);
- wait for queued ingestion before triggering work which needs the new data; and
- alert when the source has stopped producing data or verification fails.

Reposting identical data is safe: unchanged beliefs are skipped.
Changing a value with the same sensor, source, event and recording time is rejected by default rather than silently overwritten.

Common problems
---------------

``401 Unauthorized``
    Check the email, password or access token.

``403 Forbidden``
    The user is authenticated but lacks permission to record data on this sensor.

``413 Payload Too Large``
    Split the file or values into smaller time windows.

``422 Unprocessable Entity``
    Inspect the response for an incompatible unit or resolution, invalid timestamps or non-numeric values.

Unexpected timestamps
    Check timezone offsets and whether the sensor floors timestamps to its event resolution.

Missing values
    JSON value lists may contain ``null`` to preserve spacing. File uploads may contain gaps if FlexMeasures can still infer a regular frequency.

Without the Python client
-------------------------

The client wraps the FlexMeasures API, so other languages can call the same endpoints.
For example, upload a file with an access token:

.. code-block:: console

    $ curl --fail-with-body \
        -H "Authorization: ${FLEXMEASURES_ACCESS_TOKEN}" \
        -F "uploaded-files=@meter-readings.xlsx" \
        -F "belief-time-measured-instantly=true" \
        "https://${FLEXMEASURES_HOST}/api/v3_0/sensors/${FLEXMEASURES_SENSOR_ID}/data/upload"

Or post values as JSON:

.. code-block:: console

    $ curl --fail-with-body \
        -H "Authorization: ${FLEXMEASURES_ACCESS_TOKEN}" \
        -H "Content-Type: application/json" \
        --data '{
            "values": [4.2, 4.8, 5.1, 4.6],
            "start": "2026-07-30T08:00:00+02:00",
            "duration": "PT1H",
            "unit": "kW"
        }' \
        "https://${FLEXMEASURES_HOST}/api/v3_0/sensors/${FLEXMEASURES_SENSOR_ID}/data"

See :ref:`api_auth` for obtaining an access token and :ref:`v3_0` for the complete endpoint reference.

.. _observations_vs_forecasts:

Measurements, forecasts and time of knowledge
----------------------------------------------

FlexMeasures stores not only an event value but also when that value became known.
This prevents a forecast or simulation from accidentally using information which was unavailable at the time.

If neither ``prior`` nor ``horizon`` is supplied, the API uses the request time as the time of knowledge.
Use ``prior`` for one fixed publication time, such as the issue time of a day-ahead price or weather forecast.
Use ``horizon`` when every value has the same relationship between its event time and recording time.
For example, ``PT0H`` means each measurement became known when its event ended,
while ``-PT1H`` represents a one-hour reporting delay.

See :ref:`prognoses` for the full explanation of ``prior`` and ``horizon``.

.. _posting_flex_states:

Next: use the ingested data
---------------------------

After ingesting measurements, prices and forecasts, you can ask FlexMeasures to forecast new data or compute optimized schedules.
Current device state, such as a battery's state of charge, may be supplied in the scheduling trigger's ``flex-model``.
See :ref:`tut_forecasting_scheduling` and :ref:`describing_flexibility` for the next steps.
