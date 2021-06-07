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

- The plugin folder contains an ``__init__.py`` file.
- In this init, you define a Blueprint object called ``<plugin folder>_bp``.
    
We'll refer to the plugin with the name of your plugin folder.


Showcase
^^^^^^^^^

Here is a showcase file which constitutes a FlexMeasures plugin called ``our_client``.

* We demonstrate adding a view, which can be rendered using the FlexMeasures base templates.
* We also showcase a CLI function which has access to the FlexMeasures `app` object. It can be called via ``flexmeasures our_client test``. 

We first create the file ``<some_folder>/our_client/__init__.py``. This means that ``our_client`` is the plugin folder and becomes the plugin name.

With the ``__init__.py`` below, plus the custom Jinja2 template, ``our_client`` is a complete plugin.

.. code-block:: python

    from flask import Blueprint, render_template, abort

    from flask_security import login_required
    from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


    our_client_bp = Blueprint('our_client', 'our_client',
                              template_folder='templates')

    our_client_bp.__version__ = "2.0"

    # Showcase: Adding a view

    @our_client_bp.route('/')
    @our_client_bp.route('/my-page')
    @login_required
    def metrics():
        msg = "I am a FlexMeasures plugin !"
        # Note that we render via the in-built FlexMeasures way
        return render_flexmeasures_template(
            "my_page.html",
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


.. note:: You can overwrite FlexMeasures routing in your plugin. In our example above, we are using the root route ``/``. FlexMeasures registers plugin routes before its own, so in this case visiting the root URL of your app will display this plugged-in view (the same you'd see at `/my-page`).

.. note:: The ``__version__`` attribute on our blueprint object is being displayed in the standard FlexMeasures UI footer, where we show loaded plugins. Of course, it can also be useful for your own maintenance.


The template would live at ``<some_folder>/our_client/templates/my_page.html``, which works just as other FlexMeasures templates (they are Jinja2 templates):

.. code-block:: html

    {% extends "base.html" %}

    {% set active_page = "my-page" %}

    {% block title %} Our client Dashboard {% endblock %}

    {% block divs %}
    
        <!-- This is where your custom content goes... -->

        {{ message }}

    {% endblock %}


.. note:: Plugin views can also be added to the FlexMeasures UI menu ― just name them in the config setting :ref:`menu-config`. In this example, add ``my-page``. This also will make the ``active_page`` setting in the above template useful (highlights the current page in the menu).

Starting the template with ``{% extends "base.html" %}`` integrates your page content into the FlexMeasures UI structure. You can also extend a different base template. For instance, we find it handy to extend ``base.html`` with a custom base template, to extend the footer, as shown below:

 .. code-block:: html

    {% extends "base.html" %}

    {% block copyright_notice %}

    Created by <a href="https://seita.nl/">Seita Energy Flexibility</a>,
    in cooperation with <a href="https://ourclient.nl/">Our Client</a>
    &copy
    <script>var CurrentYear = new Date().getFullYear(); document.write(CurrentYear)</script>.
    
    {% endblock copyright_notice %}

We'd name this file ``our_client_base.html``. Then, we'd extend our page template from ``our_client_base.html``, instead of ``base.html``.


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


Validating arguments in your CLI commands with marshmallow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Arguments to CLI commands can be validated using `marshmallow <https://marshmallow.readthedocs.io/>`_.
FlexMeasures is using this functionality (via the ``MarshmallowClickMixin`` class) and also defines some custom field schemas.
We demonstrate this here, and also show how you can add your own custom field schema:

.. code-block:: python

    from datetime import datetime
    from typing import Optional

    import click
    from flexmeasures.data.schemas.times import AwareDateTimeField
    from flexmeasures.data.schemas.utils import MarshmallowClickMixin
    from marshmallow import fields

    class CLIStrField(fields.Str, MarshmallowClickMixin):
        """
        String field validator, made usable for CLI functions.
        You could also define your own validations here.
        """

    @click.command("meet")
    @click.option(
        "--where",
        required=True,
        type=CLIStrField(),
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


Customising the login page teaser
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

 .. code-block:: bash

    SECURITY_LOGIN_USER_TEMPLATE = "my_user_login.html"
