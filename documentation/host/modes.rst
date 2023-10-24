.. _modes-dev:

Modes
============

FlexMeasures can be run in specific modes (see the :ref:`modes-config` config setting).
This is useful for certain special situations. Two are supported out of the box and we document here 
how FlexMeasures behaves differently in these modes.

Demo
-------

In this mode, the server is assumed to be used as a demonstration tool. The following adaptations therefore happen in the UI:

- [UI] Logged-in users can view queues on the demo server (usually only admins can do that)
- [UI] Demo servers often display login credentials, so visitors can try out functionality. Use the :ref:`demo-credentials-config` config setting to do this.

Play
------

In this mode, the server is assumed to be used to run simulations.

- [API] The ``restoreData`` endpoint is registered, enabling database resets through the API.
- [UI] On the asset page, the ``sensors_to_show`` attribute can be used to show any sensor from any account, rather than only sensors from assets owned by the user's organization.

.. note:: A former feature of play mode is now a separate config setting. To allow overwriting existing data when saving data to the database, use :ref:`overwrite-config`.
