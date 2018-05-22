from flask import Flask
from flask_mail import Mail
from flask_sslify import SSLify
from flask_migrate import Migrate
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
import click

import bvp.database as database
from bvp.utils import install_secret_key
from bvp.utils.config_utils import read_config, configure_logging


"""
Prepare the Flask application object, configure logger and session.
"""


def create_app(environment=None):
    """
    Create a Flask app and configure it.
    The environment name is usually gotten from environment variable (BVP_ENVIRONMENT), but can be overwritten here
    (e.g. fore testing).
    """
    configure_logging()
    new_app = Flask(__name__)
    new_app.config['LOGGER_HANDLER_POLICY'] = 'always'  # 'always' (default), 'never',  'production', 'debug'
    new_app.config['LOGGER_NAME'] = 'bvp'  # define which logger to use for Flask

    # Some basic security measures

    install_secret_key(new_app)
    sslify = SSLify(new_app)

    # Configuration

    read_config(new_app, environment=environment)
    if new_app.debug:
        print(new_app.config)

    # Database handling

    database.configure_db(new_app)
    migrate = Migrate(new_app, database.db)

    # Setup Flask-Security for user authentication & authorization

    from bvp.models.user import User, Role, remember_login
    user_datastore = SQLAlchemySessionUserDatastore(database.db.session, User, Role)
    new_app.security = Security(new_app, user_datastore)
    user_logged_in.connect(remember_login)
    mail = Mail(new_app)

    # Register the UI

    from bvp.ui import register_at as register_ui_at
    register_ui_at(new_app)

    # Register the API

    from bvp.api import register_at as register_api_at
    register_api_at(new_app)

    # Register some useful custom scripts with the flask cli

    # @new_app.before_first_request
    @new_app.cli.command()
    @click.option("--measurements/--no-measurements", default=False, help="Add measurements. May take long.")
    def db_populate(measurements: bool):
        """Initialize the database with some static values."""
        from bvp.scripts import db_content
        click.echo('Populating the database ...')
        db_content.populate(new_app, measurements)

    @new_app.cli.command()
    @click.option("--force/no-force", default=False, help="Skip warning about consequences.")
    @click.option("--measurements/--no-measurements", default=False, help="Delete measurements.")
    def db_depopulate(measurements: bool):
        """Remove all values."""
        from bvp.scripts import db_content
        click.echo('Depopulating the database ...')
        db_content.depopulate(new_app, measurements)

    return new_app


app = create_app()