.. _view_asset-data:

*********************
Assets & sensor data
*********************

Asset page
------------

The asset page allows to see data from the asset's sensors, and also to edit attributes of the asset, like its location.
Other attributes are stored as a JSON string, which can be edited here as well.
This is meant for meta information that may be used to customize views or functionality, e.g. by plugins.
This includes the possibility to specify which sensors the asset page should show. For instance, here we include a price sensor from a public asset, by setting ``{"sensor_to_show": [3, 2]}`` (sensor 3 on top, followed by sensor 2 below).


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset.png
    :align: center
..    :scale: 40%

|
|

.. note:: It is possible to overlay data for multiple sensors, by setting the `sensors_to_show` attribute to a nested list. For example, ``{"sensor_to_show": [3, [2, 4]]}`` would show the data for sensor 4 laid over the data for sensor 2.
.. note:: While it is possible to show an arbitrary number of sensors this way, we recommend showing only the most crucial ones for faster loading, less page scrolling, and generally, a quick grasp of what the asset is up to.
.. note:: Asset attributes can be edited through the CLI as well, with the CLI command ``flexmeasures edit attribute``.


Sensor page
-------------

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