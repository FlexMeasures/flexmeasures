.. _ui_support_api:

UI-support endpoints
====================

These endpoints serve FlexMeasures' own UI, which is deployed together with the server.
They are not part of the official API, and not meant for external UIs, so they may change in any FlexMeasures version without notice.
To build on FlexMeasures, use the official API (see :ref:`v3_0`).

Summary
-------

.. qrefflask:: flexmeasures.app:create(env="documentation")
    :modules: flexmeasures.api.ui.sensors
    :undoc-endpoints: LegacyDevSensorAPI:get, LegacyDevSensorAPI:get_chart, LegacyDevSensorAPI:get_chart_data, LegacyDevSensorAPI:get_chart_annotations, LegacyDevAssetAPI:get
    :order: path
    :include-empty-docstring:

API Details
-----------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :modules: flexmeasures.api.ui.sensors
    :undoc-endpoints: LegacyDevSensorAPI:get, LegacyDevSensorAPI:get_chart, LegacyDevSensorAPI:get_chart_data, LegacyDevSensorAPI:get_chart_annotations, LegacyDevAssetAPI:get
    :order: path
    :include-empty-docstring:
