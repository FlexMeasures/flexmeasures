.. plugins:

Writing Plugins
====================

You can extend FlexMeasures with functionality like UI pages or CLI functions.

A FlexMeasures plugin works as a `Flask Blueprint <https://flask.palletsprojects.com/en/1.1.x/tutorial/views/>`_.

.. todo:: We'll use this to allow for custom forecasting and scheduling algorithms, as well.


How it works 
^^^^^^^^^^^^^^

Use the setting :ref:`plugin-config` to point to your plugin.

Here are the assumptions FlexMeasures makes to be able to import the Blueprint:

- We'll use the name of your plugin folder as the name.
- Your plugin folder contains an 'fmplugin' folder with an __init__.py file.
- In this init, you define a Blueprint object called `<plugin folder>_bp`.


Showcase
^^^^^^^^^

Here is a showcase file which constitutes a FlexMeasures plugin.

We created the file ``<some_folder>/our_client/fmplugin/__init__.py``. So, ``our_client`` is the plugin folder and becomes the plugin name.
All else that is needed for this showcase (not shown here) is ``<some_folder>/our_client/fmplugin/templates/metrics.html``, which works just as other FlexMeasures templates (they are Jinja2 templates).

We demonstrate adding a view which can be rendered via the FlexMeasures base templates. When added to the FlexMeasures UI menu (name it in :ref:`menu-config`).

We also showcase a CLI function which has access to the FlexMeasures `app` object. It can be called via ``flexmeasures our_client test``. 

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
