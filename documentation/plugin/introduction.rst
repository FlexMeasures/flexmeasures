.. _plugins:

Writing Plugins
====================

You can extend FlexMeasures with functionality like UI pages, API endpoints, CLI functions and custom scheduling algorithms.
This is eventually how energy flexibility services are built on top of FlexMeasures!

In an nutshell, a FlexMeasures plugin adds functionality via one or more `Flask Blueprints <https://flask.palletsprojects.com/en/1.1.x/tutorial/views/>`_.


How to make FlexMeasures load your plugin
------------------------------------------

Use the config setting :ref:`plugin-config` to list your plugin(s).

A setting in this list can:

1. point to a plugin folder containing an __init__.py file
2. be the name of an installed module (i.e. in a Python console `import <module_name>` would work)

Each plugin defines at least one Blueprint object. These will be registered with the Flask app,
so their functionality (e.g. routes) becomes available.

We'll discuss an example below.

In that example, we use the first option from above to tell FlexMeasures about the plugin. It is the simplest way to start playing around.

The second option (the plugin being an importable Python package) allows for more professional software development. For instance, it is more straightforward in that case to add code hygiene, version management and dependencies (your plugin can depend on a specific FlexMeasures version and other plugins can depend on yours).

To hit the ground running with that approach, we provide a `CookieCutter template <https://github.com/FlexMeasures/flexmeasures-plugin-template>`_.
It also includes a few Blueprint examples and best practices.


Continue reading the :ref:`plugin_showcase` or possibilities to do :ref:`plugin_customization`.