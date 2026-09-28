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

The **From** and **Until** fields show the time range the label will cover. They follow the range visible in the chart, until you choose one yourself:

- Pick the select tool (the double arrow above the chart), then drag across the events you want to annotate. You can drag or resize the selection afterwards, and a click on the chart clears it. Hold Ctrl to pan while the select tool is active.
- Or type the times into the **From** and **Until** fields.

A range selected on the chart, or followed from the visible chart, is widened to whole events, so the label covers every event it touches. Times you type are used as they are.

Histogram and heatmap charts have no time axis to select on, so there the fields follow the date range selected on the left.

Deleting annotations
--------------------

Users who may delete a sensor can delete its annotations from the **Delete data** panel, by choosing **Annotations** under **What**. Annotations lying entirely between the **From** and **Until** times are deleted; leave both empty to delete all of the sensor's annotations. Annotations of the sensor's asset are not affected, and an annotation that is also registered elsewhere, such as on another sensor, is only removed from this sensor.
