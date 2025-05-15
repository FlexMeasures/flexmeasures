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
