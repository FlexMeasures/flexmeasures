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


Sensors to show on a graph
^^^^^^^^^^^^^^^^^^^^^^^^^

Use the "Add Graph" button to create graphs. For each graph, you can select one or more sensors, from all available sensors associated with the asset, including public sensors, and add them to your plot.  

You can overlay data from multiple sensors on a single graph. To do this, click on an existing plot and add more sensors from the available options on the right. 

Finally, it is possible to set custom titles for any sensor graph by clicking on the "edit" button right next to the default or current title.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editgraph.png
    :align: center
..    :scale: 40%

Internally, the asset has a `sensors_to_show`` field, which controls which sensor data appears in the plot. This can also be set by a script. The accepted format is a dictionary with a graph title and a lists of sensor IDs (e.g. `[{"title": "Power", "sensor": 2}, {"title": "Costs", "sensors": [5,6] }]`). 


Editing an asset's flex-context
=========================

|
.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editflexcontext.png
    :align: center
..    :scale: 40%
|

Per asset, you can set fields in :ref:the flex-context <flex_context>, which will influence how scheduling works on this asset. The flex context dialogue allows you to define either fixed values or sensors (for dynamic values / time series). Initially, no fields are set.

Overview
--------

* **Left Panel:** Displays a list of currently configured fields.
* **Right Panel:** Shows details of the selected field and provides a form to modify its value.

Adding a field
--------------

1.  **Select Field:** Choose the desired field from the dropdown menu in the top right corner of the modal.
2.  **Add Field:** Click the "Add Field" button next to the dropdown.
3.  The field will be added to the list in the left panel.

Setting a field value
----------------------

1.  **Select Field (if it is not selected yet):** Click on the field in the left panel.
2.  **Set Value:** In the right panel, use the provided form to set the field's value.

    * Some fields may only accept a sensor value.
    * Other fields may accept either a sensor or a fixed value.

|


Status page
^^^^^^^^^^^^

For each asset, you can also visit a status page to see if your data connectivity and recent jobs are okay. At the moment, all sensors on the asset and from its flex context are tracked. Below is a fictious example, where the toy battery (from our tutorial) has schedules discharging data, but also some added by a user, and wind production data is part of the battery's flex context. There have been three succesful scheduling jobs.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/toy-schedule/screenshot_building_status.png
    :align: center
..    :scale: 40%


Audit log 
^^^^^^^^^

The audit log lets you see who made what changes to the asset over time. 
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
