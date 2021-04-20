import os
import sys
import importlib.util

import click
from flask import Flask
from flask.cli import FlaskGroup

from flexmeasures.app import create as create_app


@click.group(cls=FlaskGroup, create_app=create_app)
def flexmeasures_cli():
    """Management scripts for the FlexMeasures platform."""
    pass


def set_secret_key(app, filename="secret_key"):
    """Set the SECRET_KEY or exit.

    We first check if it is already in the config.

    Then we look for it in environment var SECRET_KEY.

    Finally, we look for `filename` in the app's instance directory.

    If nothing is found, we print instructions
    to create the secret and then exit.
    """
    secret_key = app.config.get("SECRET_KEY", None)
    if secret_key is not None:
        return
    secret_key = os.environ.get("SECRET_KEY", None)
    if secret_key is not None:
        app.config["SECRET_KEY"] = secret_key
        return
    filename = os.path.join(app.instance_path, filename)
    try:
        app.config["SECRET_KEY"] = open(filename, "rb").read()
    except IOError:
        app.logger.error(
            """
        Error:  No secret key set.

        You can add the SECRET_KEY setting to your conf file (this example works only on Unix):

        echo "SECRET_KEY=\\"`head -c 24 /dev/urandom`\\"" >> your-flexmeasures.cfg

        OR you can add an env var:

        export SECRET_KEY=xxxxxxxxxxxxxxx
        (on windows, use "set" instead of "export")

        OR you can create a secret key file (this example works only on Unix):

        mkdir -p %s
        head -c 24 /dev/urandom > %s

        You can also use Python to create a good secret:

        python -c "import secrets; print(secrets.token_urlsafe())"

        """
            % (os.path.dirname(filename), filename)
        )

        sys.exit(2)


def register_plugins(app: Flask):
    """
    Register FlexMeasures plugins as Blueprints.
    This is configured by the config setting FLEXMEASURES_PLUGIN_PATHS.

    Assumptions:
    - Your plugin folders contains an __init__.py file.
    - In this init, you define a Blueprint object called <plugin folder>_bp

    We'll refer to the plugins with the name of your plugin folders (last part of tthe path).
    """
    plugin_paths = app.config.get("FLEXMEASURES_PLUGIN_PATHS", "")
    if not isinstance(plugin_paths, list):
        app.logger.warning(
            f"The value of FLEXMEASURES_PLUGIN_PATHS is not a list: {plugin_paths}. Cannot install plugins ..."
        )
        return
    for plugin_path in plugin_paths:
        plugin_name = plugin_path.split("/")[-1]
        if not os.path.exists(os.path.join(plugin_path, "__init__.py")):
            app.logger.warning(
                f"Plugin {plugin_name} does not contain an '__init__.py' file. Cannot load plugin {plugin_name}."
            )
            return
        app.logger.debug(f"Importing plugin {plugin_name} ...")
        spec = importlib.util.spec_from_file_location(
            plugin_name, os.path.join(plugin_path, "__init__.py")
        )
        app.logger.debug(spec)
        module = importlib.util.module_from_spec(spec)
        app.logger.debug(module)
        sys.modules[plugin_name] = module
        spec.loader.exec_module(module)
        app.register_blueprint(getattr(module, f"{plugin_name}_bp"))
