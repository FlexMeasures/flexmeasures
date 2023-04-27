.. _view_asset-data:

**************
Assets & data
**************

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

