.. _view_sensors:

*********************
Sensors
*********************


Each sensor also has its own page:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_sensor.png
    :align: center
..    :scale: 40%

|
|

Next to line plots, data can sometimes be more usefully displayed as heatmaps.
Heatmaps are great ways to spot the hotspots of activity. Usually heatmaps are actually geographical maps. In our context, the most interesting background is time ― so we'd like to see activity hotspots on a map of time intervals.

We chose the "time map" of weekdays. From our experience, this is where you see the most interesting activity hotspots at a glance. For instance, that mornings often experience peaks. Or that Tuesday afternoons have low energy use, for some reason.

Here is what it looks like for one week of temperature data:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/heatmap-week-temperature.png
    :align: center
    
It's easy to see which days had milder temperatures.

And here are 4 days of (dis)-charging patterns in Seita's V2GLiberty project:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/heatmap-week-charging.png
    :align: center
    
Charging (blue) mostly happens in sunshine hours, discharging during high-price hours (morning & evening)

So on a technical level, the daily heatmap is essentially a heatmap of the sensor's values, with dates on the y-axis and time of day on the x-axis. For individual devices, it gives an insight into the device's running times. A new button lets users switch between charts.

.. _view_sensors_forecast_button:

Creating a forecast
-------------------

Users with permission to record data on a sensor can create a forecast directly from the sensor page by clicking the **Create forecast** button in the left side panel. The forecast duration defaults to 48 hours (configured via ``FLEXMEASURES_PLANNING_HORIZON``) but can be adjusted up to 7 days in the panel. The button is enabled once the sensor has at least two days of historical data. After clicking, a background job is queued and the page shows progress updates via status messages. When the job finishes, the chart is refreshed to display the new forecast alongside the historical data.

See :ref:`forecasting` for more details on how FlexMeasures generates forecasts.

Annotating sensor data
----------------------

Users with permission to record data on a sensor can add a label from the **Annotate** panel on its page. Enter a label and click **Annotate**. FlexMeasures records the annotation with the signed-in user as its data source and shows it on the time chart.

The label applies to the time interval currently visible in the chart. To annotate one belief or a small range, select that part of the time chart with the mouse to zoom in, then enter the label. Without a zoom selection, the label covers the date range selected on the left. Histogram and heatmap charts use that selected date range because they do not have a time axis to zoom into.
