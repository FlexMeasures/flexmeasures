.. _plugins:

Writing Plugins
====================

You can extend FlexMeasures with functionality like UI pages, API endpoints, or CLI functions.
This is eventually how energy flexibility services are built on top of FlexMeasures!

In an nutshell, a FlexMeasures plugin adds functionality via one or more `Flask Blueprints <https://flask.palletsprojects.com/en/1.1.x/tutorial/views/>`_.

.. todo:: We'll use this to allow for custom forecasting and scheduling algorithms, as well.


How to make FlexMeasures load your plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use the config setting :ref:`plugin-config` to list your plugin(s).

A setting in this list can:

1. point to a plugin folder containing an __init__.py file
2. be the name of an installed module (i.e. in a Python console `import <module_name>` would work)

Each plugin defines at least one Blueprint object. These will be registered with the Flask app,
so their functionality (e.g. routes) becomes available.

We'll discuss an example below.

In that example, we use the first option from above to tell FlexMeasures about the plugin. It is the simplest way to start playing around.

The second option (the plugin being an importable Python package) allows for more professional software development. For instance, it is more straightforward in that case to add code hygiene, version management and dependencies (your plugin can depend on a specific FlexMeasures version and other plugins can depend on yours).

To hit the ground running with that approach, we provide a `CookieCutter template <https://github.com/SeitaBV/flexmeasures-plugin-template>`_.
It also includes a few Blueprint examples and best practices.


Showcase
^^^^^^^^^

Here is a showcase file which constitutes a FlexMeasures plugin called ``our_client``.

* We demonstrate adding a view, which can be rendered using the FlexMeasures base templates.
* We also showcase a CLI function which has access to the FlexMeasures `app` object. It can be called via ``flexmeasures our-client test``. 

We first create the file ``<some_folder>/our_client/__init__.py``. This means that ``our_client`` is the plugin folder and becomes the plugin name.

With the ``__init__.py`` below, plus the custom Jinja2 template, ``our_client`` is a complete plugin.

.. code-block:: python

    __version__ = "2.0"

    from flask import Blueprint, render_template, abort

    from flask_security import login_required
    from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


    our_client_bp = Blueprint('our-client', __name__,
                              template_folder='templates')

    # Showcase: Adding a view

    @our_client_bp.route('/')
    @our_client_bp.route('/my-page')
    @login_required
    def my_page():
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
    def our_client_test():
        print(f"I am a CLI command, part of FlexMeasures: {current_app}")


.. note:: You can overwrite FlexMeasures routing in your plugin. In our example above, we are using the root route ``/``. FlexMeasures registers plugin routes before its own, so in this case visiting the root URL of your app will display this plugged-in view (the same you'd see at `/my-page`).

.. note:: The ``__version__`` attribute on our module is being displayed in the standard FlexMeasures UI footer, where we show loaded plugins. Of course, it can also be useful for your own maintenance.


The template would live at ``<some_folder>/our_client/templates/my_page.html``, which works just as other FlexMeasures templates (they are Jinja2 templates):

.. code-block:: html

    {% extends "base.html" %}

    {% set active_page = "my-page" %}

    {% block title %} Our client dashboard {% endblock %}

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


Adding your own stylesheets
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can style your plugin's pages in a distinct way by adding your own style-sheet. This happens by overwriting FlexMeasures ``styles`` block. Add to your plugin's base template (see above):

.. code-block:: html 

{% block styles %}
 {{ super() }}
 <!-- Our client styles -->
 <link rel="stylesheet" href="{{ url_for('our_client_bp.static', filename='css/style.css')}}">
{% endblock %}

This will find `css/styles.css` if you add that folder and file to your Blueprint's static folder.

.. note:: This styling will only apply to the pages defined in your plugin (to pages based on your own base template). To apply a styling to all other pages which are served by FlexMeasures, consider using the config setting :ref:`extra-css-config`. 



Using other code files in your non-package plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Say you want to include other Python files in your plugin, importing them in your ``__init__.py`` file.
With this file-only version of loading the plugin (if your plugin isn't imported as a package),
this is a bit tricky.

But it can be achieved if you put the plugin path on the import path. Do it like this in your ``__init__.py``:

.. code-block:: python

    import os
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)

    from my_other_file import my_function


Using a custom favicon icon
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The favicon might be an important part of your customisation. You probably want your logo to be used.

First, your blueprint needs to know about a folder with static content (this is fairly common ― it's also where you'd put your own CSS or JavaScript files):

.. code-block:: python

    our_client_bp = Blueprint(
        "our_client",
        "our_client",
        static_folder="our_client/ui/static",
    )

Put your icon file in that folder. The exact path may depend on how you set your plugin directories up, but this is how a blueprint living in its own directory could work.

Then, overwrite the ``/favicon.ico`` route which FlexMeasures uses to get the favicon from:

.. code-block:: python

    from flask import send_from_directory

    @our_client_bp.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            our_client_bp.static_folder,
            "img/favicon.png",
            mimetype="image/png",
        )

Here we assume your favicon is a PNG file. You can also use a classic `.ico` file, then your mime type probably works best as ``image/x-icon``.


Notes on writing tests for your plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Good software practice is to write automatable tests. We encourage you to also do this in your plugin.
We do, and our CookieCutter template for plugins (see above) has simple examples how that can work for the different use cases
(i.e. UI, API, CLI).

However, there are two caveats to look into:

* Your tests need a FlexMeasures app context. FlexMeasure's app creation function provides a way to inject a list of plugins directly. The following could be used for instance in your ``app`` fixture within the top-level ``conftest.py`` if you are using pytest:

.. code-block:: python

    from flexmeasures.app import create as create_flexmeasures_app
    from .. import __name__

    test_app = create_flexmeasures_app(env="testing", plugins=[f"../"{__name__}])

* Test frameworks collect tests from your code and therefore might import your modules. This can interfere with the registration of routes on your Blueprint objects during plugin registration. Therefore, we recommend reloading your route modules, after the Blueprint is defined and before you import them. For example:

.. code-block:: python

    my_plugin_ui_bp: Blueprint = Blueprint(
        "MyPlugin-UI",
        __name__,
        template_folder="my_plugin/ui/templates",
        static_folder="my_plugin/ui/static",
        url_prefix="/MyPlugin",
    )
    # Now, before we import this dashboard module, in which the "/dashboard" route is attached to my_plugin_ui_bp,
    # we make sure it's being imported now, *after* the Blueprint's creation.
    importlib.reload(sys.modules["my_plugin.my_plugin.ui.views.dashboard"])
    from my_plugin.ui.views import dashboard

The packaging path depends on your plugin's package setup, of course.


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
