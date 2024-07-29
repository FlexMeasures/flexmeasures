.. _plugin_customization:


Plugin Customizations
=======================


Adding your own scheduling algorithm
-------------------------------------

FlexMeasures comes with in-built scheduling algorithms for often-used use cases. However, you can use your own algorithm, as well.

The idea is that you'd still use FlexMeasures' API to post flexibility states and trigger new schedules to be computed (see :ref:`posting_flex_states`),
but in the background your custom scheduling algorithm is being used.

Let's walk through an example!

First, we need to write a a class (inhering from the Base Scheduler) with a `schedule` function which accepts arguments just like the in-built schedulers (their code is `here <https://github.com/FlexMeasures/flexmeasures/tree/main/flexmeasures/data/models/planning>`_).
The following minimal example gives you an idea of some meta information you can add for labeling your data, as well as the inputs and outputs of such a scheduling function:

.. code-block:: python

    from datetime import datetime, timedelta
    import pandas as pd
    from pandas.tseries.frequencies import to_offset
    from flexmeasures import Scheduler, Sensor


    class DummyScheduler(Scheduler):

        __author__ = "My Company"
        __version__ = "2"

        def compute(
            self,
            *args,
            **kwargs
        ):
            """
            Just a dummy scheduler that always plans to consume at maximum capacity.
            (Schedulers return positive values for consumption, and negative values for production)
            """
            return pd.Series(
                self.sensor.get_attribute("capacity_in_mw"),
                index=pd.date_range(self.start, self.end, freq=self.resolution, inclusive="left"),
            )
    
        def deserialize_config(self):
            """Do not care about any flex config sent in."""
            self.config_deserialized = True


.. note:: It's possible to add arguments that describe the asset flexibility model and the flexibility (EMS) context in more detail.
          For example, for storage assets we support various state-of-charge parameters. For details on flexibility model and context,
          see :ref:`describing_flexibility` and the `[POST] /sensors/(id)/schedules/trigger <../api/v3_0.html#post--api-v3_0-sensors-(id)-schedules-trigger>`_ endpoint.
        

Finally, make your scheduler be the one that FlexMeasures will use for certain sensors:


.. code-block:: python

    from flexmeasures import Sensor

    scheduler_specs = {
        "module": "flexmeasures.data.tests.dummy_scheduler",  # or a file path, see note below
        "class": "DummyScheduler",
    }
    
    my_sensor = Sensor.query.filter(Sensor.name == "My power sensor on a flexible asset").one_or_none()
    my_sensor.attributes["custom-scheduler"] = scheduler_specs


From now on, all schedules (see :ref:`tut_forecasting_scheduling`) which are requested for this sensor should
get computed by your custom function! For later lookup, the data will be linked to a new data source with the name "My Opinion".

.. note:: To describe the module, we used an importable module here (actually a custom scheduling function we use to test this).
          You can also provide a full file path to the module, e.g. "/path/to/my_file.py".


.. todo:: We're planning to use a similar approach to allow for custom forecasting algorithms, as well.


Deploying your plugin via Docker
----------------------------------

You can extend the FlexMeasures Docker image with your plugin's logic.

Imagine your plugin package (with an ``__init__.py`` file, one of the setups we discussed in :ref:`plugin_showcase`) is called ``flexmeasures_testplugin``.
Then, this is a minimal possible Dockerfile ― containers based on this will serve FlexMeasures (see the original Dockerfile in the FlexMeasures repository) with the plugin logic, like endpoints:

.. code-block:: docker

    FROM lfenergy/flexmeasures

    COPY flexmeasures_testplugin/ /app/flexmeasures_testplugin
    ENV FLEXMEASURES_PLUGINS="/app/flexmeasures_testplugin"

You can of course also add multiple plugins this way.

If you also want to install your requirements, you could for instance add these layers:

.. code-block:: docker

    COPY requirements/app.in /app/requirements/flexmeasures_testplugin.txt
    RUN pip3 install --no-cache-dir -r requirements/flexmeasures_testplugin.txt

.. note:: No need to install flexmeasures here, as the Docker image we are based on already installed FlexMeasures from code. If you pip3-install your plugin here (assuming it's on Pypi), check if it recognizes that FlexMeasures installation as it should.



Adding your own style sheets
----------------------------

You can style your plugin's pages in a distinct way by adding your own style-sheet. This happens by overwriting FlexMeasures ``styles`` block. Add to your plugin's base template (see above):

.. code-block:: html 

    {% block styles %}
        {{ super() }}
        <!-- Our client styles -->
        <link rel="stylesheet" href="{{ url_for('our_client_bp.static', filename='css/style.css')}}">
    {% endblock %}

This will find `css/styles.css` if you add that folder and file to your Blueprint's static folder.

.. note:: This styling will only apply to the pages defined in your plugin (to pages based on your own base template). To apply a styling to all other pages which are served by FlexMeasures, consider using the config setting :ref:`extra-css-config`. 


Adding config settings
----------------------------

FlexMeasures can automatically check for you if any custom config settings, which your plugin is using, are present.
This can be very useful in maintaining installations of FlexMeasures with plugins.
Config settings can be registered by setting the (optional) ``__settings__`` attribute on your plugin module:

.. code-block:: python

    __settings__ = {
        "MY_PLUGIN_URL": {
            "description": "URL used by my plugin for x.",
            "level": "error",
        },
        "MY_PLUGIN_TOKEN": {
            "description": "Token used by my plugin for y.",
            "level": "warning",
            "message_if_missing": "Without this token, my plugin will not do y.",
            "parse_as": str,
        },
        "MY_PLUGIN_COLOR": {
            "description": "Color used to override the default plugin color.",
            "level": "info",
        },
    }

Alternatively, use ``from my_plugin import __settings__`` in your plugin module, and create ``__settings__.py`` with:

.. code-block:: python

    MY_PLUGIN_URL = {
        "description": "URL used by my plugin for x.",
        "level": "error",
    }
    MY_PLUGIN_TOKEN = {
        "description": "Token used by my plugin for y.",
        "level": "warning",
        "message_if_missing": "Without this token, my plugin will not do y.",
        "parse_as": str,
    }
    MY_PLUGIN_COLOR = {
        "description": "Color used to override the default plugin color.",
        "level": "info",
    }

Finally, you might want to override some FlexMeasures configuration settings from within your plugin.
Some examples for possible settings are named on this page, e.g. the custom style (see above) or custom logo (see below).
There is a `record_once` function on Blueprints which can help with this. An example:

.. code-block:: python

    @our_client_bp.record_once
    def record_logo_path(setup_state):
        setup_state.app.config[
            "FLEXMEASURES_MENU_LOGO_PATH"
        ] = "/path/to/my/logo.svg"
    


Using a custom favicon icon
----------------------------

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
    from flexmeasures.ui import flexmeasures_ui

    @flexmeasures_ui.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            our_client_bp.static_folder,
            "img/favicon.png",
            mimetype="image/png",
        )

Here we assume your favicon is a PNG file. You can also use a classic `.ico` file, then your mime type probably works best as ``image/x-icon``.


Validating arguments in your CLI commands with marshmallow
-----------------------------------------------------------

Arguments to CLI commands can be validated using `marshmallow <https://marshmallow.readthedocs.io/>`_.
FlexMeasures is using this functionality (via the ``MarshmallowClickMixin`` class) and also defines some custom field schemas.
We demonstrate this here, and also show how you can add your own custom field schema:

.. code-block:: python

    from datetime import datetime

    import click
    from flexmeasures.data.schemas import AwareDateTimeField
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
        when: datetime | None = None,
    ):
        print(f"Okay, see you {where} on {when}.")


Customising the login page teaser
----------------------------------

FlexMeasures shows an image carousel next to its login form (see ``ui/templates/admin/login_user.html``).

You can overwrite this content by adding your own login template and defining the ``teaser`` block yourself, e.g.:

.. code-block:: html

    {% extends "admin/login_user.html" %}

    {% block teaser %}

        <h1>Welcome to my plugin!</h1>

    {% endblock %}

Place this template file in the template folder of your plugin blueprint (see above). Your template must have a different filename than "login_user", so FlexMeasures will find it properly!

Finally, add this config setting to your FlexMeasures config file (using the template filename you chose, obviously):

 .. code-block:: python

    SECURITY_LOGIN_USER_TEMPLATE = "my_user_login.html"
