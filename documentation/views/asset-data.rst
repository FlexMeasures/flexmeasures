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

The data charts are maybe the most interesting feature - they form your own data dashboard. When the most interesting sensors are shown, the replay button on the right creates a very meaningful dynamic insight!


Sensors to show on Graph
^^^^^^^^^^^^^^^^^^^^^^^^^

Use the "Add Graph" button to create graphs. For each graph, you can select one or more sensors, from all available sensors associated with the asset, including public sensors, and add them to your plot.  

You can overlay data from multiple sensors on a single graph. To do this, click on an existing plot and add more sensors from the available options on the right. 

Finally, it is possible to set custom titles for any sensor graph by clicking on the "edit" button right next to the default or current title.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editgraph.png
    :align: center
..    :scale: 40%

Internally, the asset has a `sensors_to_show`` field, which controls which sensor data appears in the plot. This can also be set by a script. Accepted formats are simple lists of sensor IDs (e.g. `[2, [5,6]]` or a more expressive format (e.g. `[{"title": "Power", "sensor": 2}, {"title": "Costs", "sensors": [5,6] }`). 


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
