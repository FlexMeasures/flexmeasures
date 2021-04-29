.. _plugins:

Writing Plugins
====================

You can extend FlexMeasures with functionality like UI pages or CLI functions.

A FlexMeasures plugin works as a `Flask Blueprint <https://flask.palletsprojects.com/en/1.1.x/tutorial/views/>`_.

.. todo:: We'll use this to allow for custom forecasting and scheduling algorithms, as well.


How it works 
^^^^^^^^^^^^^^

Use the config setting :ref:`plugin-config` to point to your plugin(s).

Here are the assumptions FlexMeasures makes to be able to import your Blueprint:

- The plugin folder contains an __init__.py file.
- In this init, you define a Blueprint object called ``<plugin folder>_bp``.
    
We'll refer to the plugin with the name of your plugin folder.


Showcase
^^^^^^^^^

Here is a showcase file which constitutes a FlexMeasures plugin. We imagine that we made a plugin to implement some custom logic for a client. 

We created the file ``<some_folder>/our_client/__init__.py``. So, ``our_client`` is the plugin folder and becomes the plugin name.
All else that is needed for this showcase (not shown here) is ``<some_folder>/our_client/templates/metrics.html``, which works just as other FlexMeasures templates (they are Jinja2 templates and you can start them with ``{% extends "base.html" %}`` for integration into the FlexMeasures structure).


* We demonstrate adding a view which can be rendered via the FlexMeasures base templates.
* We also showcase a CLI function which has access to the FlexMeasures `app` object. It can be called via ``flexmeasures our_client test``. 

.. code-block:: python

    from flask import Blueprint, render_template, abort

    from flask_security import login_required
    from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


    our_client_bp = Blueprint('our_client', 'our_client',
                              template_folder='templates')


    # Showcase: Adding a view

    @our_client_bp.route('/metrics')
    @login_required
    def metrics():
        msg = "I am part of FM !"
        # Note that we render via the in-built FlexMeasures way
        return render_flexmeasures_template(
            "metrics.html",
            message=msg,
        )


    # Showcase: Adding a CLI command

    import click
    from flask import current_app
    from flask.cli import with_appcontext


    our_client_bp.cli.help = "Our client commands"

    @our_client_bp.cli.command("test")
    @with_appcontext
    def oc_test():
        print(f"I am a CLI command, part of FlexMeasures: {current_app}")



.. note:: Plugin views can also be added to the FlexMeasures UI menu ― just name them in the config setting :ref:`menu-config`.


Using other files in your plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Say you want to include other Python files in your plugin, importing them in your ``__init__.py`` file.
This can be done if you put the plugin path on the import path. Do it like this in your ``__init__.py``:

.. code-block:: python

    import os
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)

    from my_other_file import my_function