.. _view_asset-data:

*********************
Assets  
*********************

The asset page is divided into different views. The default selection is the "Context" view. The views are:

.. contents::
    :local:
    :depth: 1
|


.. _view_asset_context:

Context page
-------------------


On the context page, you see the asset in its structure (with its parent and children, if they exist), or its location on a map.
In addition, you can do the following:

- Click the "Show sensors" button to view the list of the sensors associated with the asset.
- Click "Edit flex-context" to edit the flex-context of the asset.
- Click the "Add child asset" button to add a child to the current asset.
- Set a given page as default by clicking the checkbox on the top right of the page.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_context.png
    :align: center
..    :scale: 40%

|


Show sensors
^^^^^^^^^^^^
The sensors associated with the asset are shown in a list. 

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_sensors.png
    :align: center
..   :scale: 40%

|


Editing an asset's flex-context
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


Per asset, you can set fields in :ref:`the flex-context <flex_context>`, which will influence how scheduling works on this asset. The flex context dialogue allows you to define either fixed values or sensors (for dynamic values / time series). Initially, no fields are set.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editflexcontext.png
    :align: center
..    :scale: 40%

|

Flex context overview
"""""""""""""""""""""""

* **Left Panel:** Displays a list of currently configured fields.
* **Right Panel:** Shows details of the selected field and provides a form to modify its value.

Adding a field
"""""""""""""""
1.  **Select Field:** Choose the desired field from the dropdown menu in the top right corner of the modal.
2.  **Add Field:** Click the "Add Field" button next to the dropdown.
3.  The field will be added to the list in the left panel.

Setting a field value
"""""""""""""""""""""

1.  **Select Field (if it is not selected yet):** Click on the field in the left panel.
2.  **Set Value:** In the right panel, use the provided form to set the field's value.

    * Some fields may only accept a sensor value.
    * Other fields may accept either a sensor or a fixed value.

|

.. _view_asset_graphs:

Graphs page
-----------

The graph page is a separate page that shows data (measurements/forecasts) which are relevant to the asset.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_graphs.png
    :align: center
..    :scale: 40%

|

Editing the graphs dashboard
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Click the "Edit Graph" button to open the graph editor.

Use the "Add Graph" button to create graphs. For each graph, you can select one or more sensors, from all available sensors associated with the asset, including public sensors, and add them to your plot.  

You can overlay data from multiple sensors on a single graph. To do this, click on an existing plot and add more sensors from the available options on the right. 

Finally, it is possible to set custom titles for any sensor graph by clicking on the "edit" button right next to the default or current title.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-asset-editgraph.png
    :align: center
..    :scale: 40%

|

Internally, the asset has a `sensors_to_show`` field, which controls which sensor data appears in the plot. This can also be set by a script. The accepted format is a dictionary with a graph title and a lists of sensor IDs (e.g. `[{"title": "Power", "sensor": 2}, {"title": "Costs", "sensors": [5,6] }]`).


.. _view_asset_properties:

Properties page
---------------

The properties page allows you to view and edit the properties of the asset.

You can also delete the asset by clicking on the "Delete this asset" button.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_asset_properties.png
    :align: center
..    :scale: 40%

|

.. _view_asset_status:

Status page
-----------

For each asset, you can also visit a status page to see if your data connectivity and recent jobs are okay.

For data connectivity, all sensors on the asset's graph page and from its flex context are tracked.

Below is a fictious example, where the toy battery (from our tutorial) has schedules discharging data, but also some added by a user, and wind production data is part of the battery's flex context. There have been three succesful scheduling jobs.

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot_status_page.png
    :align: center
..    :scale: 40%

|
   
Hovering over the traffic light will tell you how long ago this most recent entry is and why the light is red, yellow or green. For jobs, you can also get more information (e.g. error message).


.. _view_asset_auditlog:

Audit log 
---------

The audit log lets you see who made what changes to the asset over time. 
This is how the audit log looks for the history of actions taken on an asset:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/screenshot-auditlog.PNG
    :align: center
..    :scale: 40%

|

