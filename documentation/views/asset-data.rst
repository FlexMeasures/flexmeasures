.. _view_asset-data:

*********************
Assets & sensor data
*********************

Asset page
------------

The asset page allows to plot data from the asset's sensors, show sensors and child assets and also to edit attributes of the asset, like its location.

For instance, in the picture below we include a price sensor from a public asset, then plot the asset's only sensor below that.


.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset.png
    :align: center
..    :scale: 40%

|
|


The asset page as data dashboard
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The data charts are maybe the most interesting feature - turning it into a data dashboard. When the most interesting sensors are shown, the replay button on the right creates a very meaningful dynamic insight!

With the attribute `sensors_to_show` one can specify from which sensors the asset page should show data. In the example above, this happened by setting ``{"sensor_to_show": [3, 2]}`` (sensor 3 on top, followed by sensor 2 below).

It is also possible to overlay data for multiple sensors within one plot, by setting the `sensors_to_show` attribute to a nested list. For example, ``{"sensor_to_show": [3, [2, 4]]}`` would show the data for sensor 4 laid over the data for sensor 2.
While it is possible to show an arbitrary number of sensors this way, we recommend showing only the most crucial ones for faster loading, less page scrolling, and generally, a quick grasp of what the asset is up to.

Finally, it is possible to set custom titles for sensor graphs, by setting within `sensors_to_show` a dictionary with a title and sensor or sensors. For example, ``{"title": "Outdoor Temperature", "sensor": 1}`` or ``{"title": "Energy Demand", "sensors": [2, 3]}`` will display the specified title for the corresponding sensor data.



Status page
^^^^^^^^^^^^

For each asset, you can also visit a status page to see if your data connectivity and recent jobs are okay. This is how data connectivity status looks like on the building asset from our tutorial:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/screenshot_building_status.png
    :align: center
..    :scale: 40%

|
|

This is how the audit log looks for the history of actions taken on an asset:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-auditlog.PNG
    :align: center
..    :scale: 40%


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
