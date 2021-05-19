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

    @our_client_bp.route('/')
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


.. note:: You can overwrite FlexMeasures routes here. In our example above, we set the root route ``/``. FlexMeasures registers plugin routes before its own, so in this case visiting the root URL of your app will display this plugged-in view (the same you'd see at `/metrics`).

.. note:: Plugin views can also be added to the FlexMeasures UI menu ― just name them in the config setting :ref:`menu-config`.

Validating data with marshmallow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures validates input data using `marshmallow <https://marshmallow.readthedocs.io/>`_.
Data fields can be made suitable for use in CLI commands through our ``MarshmallowClickMixin``.
An example:

.. code-block:: python

    from datetime import datetime
    from typing import Optional

    import click
    from flexmeasures.data.schemas.times import AwareDateTimeField
    from flexmeasures.data.schemas.utils import MarshmallowClickMixin
    from marshmallow import fields

    class StrField(fields.Str, MarshmallowClickMixin):
        """String field validator usable for UI routes and CLI functions."""

    @click.command("meet")
    @click.option(
        "--where",
        required=True,
        type=StrField(),  # see above: we just made this field suitable for CLI functions
        help="(Required) Where we meet",
    )
    @click.option(
        "--when",
        required=False,
        type=AwareDateTimeField(format="iso"),  # FlexMeasures already made this field suitable for CLI functions
        help="[Optional] When we meet (expects timezone-aware ISO 8601 datetime format)",
    )
    def schedule_meeting(
        where: str,
        when: Optional[datetime] = None,
    ):
        print(f"Okay, see you {where} on {when}.")


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


Customising the login teaser
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

FlexMeasures shows an image carousel next to its login form (see ``ui/templates/admin/login_user.html``).

You can overwrite this content by adding your own login template and defining the ``teaser`` block yourself, e.g.:

.. code-block:: html

    {% extends "admin/login_user.html" %}

    {% block teaser %}

        <h1>Welcome to my plugin!</h1>

    {% endblock %}

Place this template file in the template folder of your plugin blueprint (see above). Your template must have a different filename than "login_user", so FlexMeasures will find it properly!

Finally, add this config setting to your FlexMeasures config file (using the template filename you chose, obviously):

    SECURITY_LOGIN_USER_TEMPLATE = "my_user_login.html"
